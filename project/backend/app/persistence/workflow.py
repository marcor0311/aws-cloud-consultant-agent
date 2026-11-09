"""Durable business events, jobs, artifacts and measured work, on SQLite or Postgres."""

import hashlib
import json
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import (
    JSON,
    Column,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    delete,
    insert,
    select,
    update,
)
from sqlalchemy.exc import IntegrityError

from app.persistence.locking import Busy

metadata = MetaData()
records = Table(
    "workflow_records",
    metadata,
    Column("key", String(512), primary_key=True),
    Column("kind", String(40), nullable=False, index=True),
    Column("payload", JSON, nullable=False),
)
events = Table(
    "workflow_events",
    metadata,
    Column("id", String(256), primary_key=True),
    Column("case_id", String(160), index=True),
    Column("kind", String(80), nullable=False),
    Column("at", Float, nullable=False),
    Column("payload", JSON, nullable=False),
)
jobs = Table(
    "workflow_jobs",
    metadata,
    Column("id", String(256), primary_key=True),
    Column("kind", String(50), nullable=False),
    Column("payload", JSON, nullable=False),
    Column("status", String(24), nullable=False),
    Column("available_at", Float, nullable=False),
    Column("lease_until", Float, nullable=False, default=0),
    Column("attempts", Integer, nullable=False, default=0),
    Column("receipt", JSON),
    Column("error", String(120)),
)
sessions = Table(
    "workflow_work_sessions",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("case_id", String(160), nullable=False, index=True),
    Column("phase", String(80), nullable=False),
    Column("actor", String(160), nullable=False),
    Column("actor_type", String(16), nullable=False),
    Column("issue_url", String(512)),
    Column("started_at", Float, nullable=False),
    Column("ended_at", Float),
)
leases = Table(
    "workflow_leases",
    metadata,
    Column("key", String(256), primary_key=True),
    Column("owner", String(64), nullable=False),
    Column("until", Float, nullable=False),
)


projects = Table(
    "workflow_projects",
    metadata,
    Column("case_id", String(160), primary_key=True),
    Column("project_id", String(160), nullable=False, unique=True),
    Column("title", String(256), nullable=False),
    Column("company", String(256), nullable=False),
    Column("manager_id", String(160), nullable=False),
    Column("opened_at", Float, nullable=False),
    Column("is_fictitious", Integer, nullable=False, default=0),
)
handoffs = Table(
    "workflow_handoffs",
    metadata,
    Column("id", String(256), primary_key=True),
    Column("case_id", String(160), nullable=False, index=True),
    Column("from_actor", String(160), nullable=False),
    Column("to_actor", String(160), nullable=False),
    Column("from_phase", String(80), nullable=False),
    Column("to_phase", String(80), nullable=False),
    Column("revision", Integer, nullable=False, default=0),
    Column("artifact_sha256", String(64)),
    Column("created_at", Float, nullable=False),
    Column("accepted_at", Float),
    Column("accepted_by", String(160)),
)
notes = Table(
    "workflow_collaboration_notes",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("case_id", String(160), nullable=False, index=True),
    Column("revision", Integer, nullable=False),
    Column("actor", String(160), nullable=False),
    Column("text", String, nullable=False),
    Column("created_at", Float, nullable=False),
)


class WorkflowStore:
    def __init__(self, url: str, clock=time.time):
        self.clock = clock
        if url.startswith("sqlite:///"):
            path = Path(url.removeprefix("sqlite:///"))
            if str(path) != ":memory:":
                path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                if not path.exists():
                    path.touch(mode=0o600)
        self.engine = create_engine(url, pool_pre_ping=True)
        metadata.create_all(self.engine)

    @staticmethod
    def put_in(db, key, kind, payload):
        if db.execute(select(records.c.key).where(records.c.key == key)).first():
            db.execute(
                update(records).where(records.c.key == key).values(payload=payload)
            )
        else:
            db.execute(insert(records).values(key=key, kind=kind, payload=payload))

    def put(self, key, kind, payload):
        with self.engine.begin() as db:
            self.put_in(db, key, kind, payload)

    def get(self, key):
        with self.engine.connect() as db:
            return db.execute(
                select(records.c.payload).where(records.c.key == key)
            ).scalar()

    def list(self, kind):
        with self.engine.connect() as db:
            return list(
                db.execute(
                    select(records.c.payload).where(records.c.kind == kind)
                ).scalars()
            )

    def event(self, event_id, case_id, kind, payload=None):
        try:
            with self.engine.begin() as db:
                db.execute(
                    insert(events).values(
                        id=event_id,
                        case_id=case_id,
                        kind=kind,
                        at=self.clock(),
                        payload=payload or {},
                    )
                )
            return True
        except IntegrityError:
            return False

    def case_events(self, case_id):
        with self.engine.connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    select(events)
                    .where(events.c.case_id == case_id)
                    .order_by(events.c.at, events.c.id)
                ).mappings()
            ]

    def register_project(
        self,
        case_id,
        project_id,
        title,
        company,
        manager_id,
        *,
        opened_at=None,
        is_fictitious=False,
    ):
        values = {
            "project_id": project_id,
            "title": title,
            "company": company,
            "manager_id": manager_id,
            "is_fictitious": int(is_fictitious),
        }
        with self.engine.begin() as db:
            if db.execute(
                select(projects.c.case_id).where(projects.c.case_id == case_id)
            ).first():
                db.execute(
                    update(projects)
                    .where(projects.c.case_id == case_id)
                    .values(**values)
                )
            else:
                db.execute(
                    insert(projects).values(
                        case_id=case_id,
                        opened_at=self.clock() if opened_at is None else opened_at,
                        **values,
                    )
                )

    def project_list(self, manager_id):
        with self.engine.connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    select(projects)
                    .where(projects.c.manager_id == manager_id)
                    .order_by(projects.c.opened_at)
                ).mappings()
            ]

    def create_handoff(
        self,
        handoff_id,
        case_id,
        from_actor,
        to_actor,
        from_phase,
        to_phase,
        *,
        revision=0,
        artifact_sha256=None,
    ):
        try:
            with self.engine.begin() as db:
                db.execute(
                    insert(handoffs).values(
                        id=handoff_id,
                        case_id=case_id,
                        from_actor=from_actor,
                        to_actor=to_actor,
                        from_phase=from_phase,
                        to_phase=to_phase,
                        revision=revision,
                        artifact_sha256=artifact_sha256,
                        created_at=self.clock(),
                    )
                )
                db.execute(
                    insert(events).values(
                        id=f"created:{handoff_id}",
                        case_id=case_id,
                        kind="handoff.created",
                        at=self.clock(),
                        payload={
                            "handoff_id": handoff_id,
                            "from_actor": from_actor,
                            "to_actor": to_actor,
                            "revision": revision,
                        },
                    )
                )
        except IntegrityError:
            pass
        return self.handoff(handoff_id)

    def handoff(self, handoff_id):
        with self.engine.connect() as db:
            row = (
                db.execute(select(handoffs).where(handoffs.c.id == handoff_id))
                .mappings()
                .first()
            )
            return dict(row) if row else None

    def case_handoffs(self, case_id):
        with self.engine.connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    select(handoffs)
                    .where(handoffs.c.case_id == case_id)
                    .order_by(handoffs.c.created_at)
                ).mappings()
            ]

    def accept_handoff(self, handoff_id, actor, accepted_at=None):
        with self.engine.begin() as db:
            row = (
                db.execute(select(handoffs).where(handoffs.c.id == handoff_id))
                .mappings()
                .first()
            )
            if not row or row["to_actor"] != actor:
                raise ValueError("La entrega no está asignada a este responsable.")
            if row["accepted_at"] is not None:
                return dict(row)
            acceptance_time = self.clock() if accepted_at is None else accepted_at
            db.execute(
                update(handoffs)
                .where(handoffs.c.id == handoff_id, handoffs.c.accepted_at.is_(None))
                .values(accepted_at=acceptance_time, accepted_by=actor)
            )
            db.execute(
                insert(events).values(
                    id=f"accepted:{handoff_id}",
                    case_id=row["case_id"],
                    kind="handoff.accepted",
                    at=acceptance_time,
                    payload={"handoff_id": handoff_id, "actor": actor},
                )
            )
        result = self.handoff(handoff_id)
        if result["to_phase"] == "stage-2":
            legacy = self.get(f"handoff:{result['case_id']}")
            if legacy and legacy["revision"] == result["revision"]:
                self.put(
                    f"handoff:{result['case_id']}",
                    "handoff",
                    {
                        **legacy,
                        "receipt": "accepted_by_stage_2",
                        "accepted_at": result["accepted_at"],
                        "accepted_by": actor,
                    },
                )
        return result

    def add_note(self, case_id, revision, actor, text):
        if not text.strip():
            raise ValueError("El comentario no puede estar vacío.")
        note_id = uuid.uuid4().hex
        with self.engine.begin() as db:
            db.execute(
                insert(notes).values(
                    id=note_id,
                    case_id=case_id,
                    revision=revision,
                    actor=actor,
                    text=text.strip(),
                    created_at=self.clock(),
                )
            )
        return note_id

    def case_notes(self, case_id):
        with self.engine.connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    select(notes)
                    .where(notes.c.case_id == case_id)
                    .order_by(notes.c.created_at)
                ).mappings()
            ]

    def set_phase_start(self, case_id, phase, accepted_at):
        key = f"phase:{case_id}:{phase}"
        current = self.get(key)
        if not current or accepted_at > current["accepted_at"]:
            raise ValueError("No se puede adelantar el inicio registrado de la etapa.")
        self.put(key, "phase", {**current, "accepted_at": accepted_at})

    def record_interval(
        self, session_id, case_id, phase, actor, actor_type, start, end
    ):
        if end < start or actor_type not in {"human", "agent"}:
            raise ValueError("Intervalo inválido.")
        with self.engine.begin() as db:
            db.execute(
                insert(sessions).values(
                    id=session_id,
                    case_id=case_id,
                    phase=phase,
                    actor=actor,
                    actor_type=actor_type,
                    started_at=start,
                    ended_at=end,
                )
            )

    def enqueue(self, key, kind, payload):
        try:
            with self.engine.begin() as db:
                db.execute(
                    insert(jobs).values(
                        id=key,
                        kind=kind,
                        payload=payload,
                        status="pending",
                        available_at=self.clock(),
                        lease_until=0,
                        attempts=0,
                    )
                )
            return True
        except IntegrityError:
            return False

    def receive(self, event_id, kind, payload):
        # ACK only after both the event and its pending job commit.
        try:
            with self.engine.begin() as db:
                db.execute(
                    insert(events).values(
                        id=event_id, kind=kind, at=self.clock(), payload=payload
                    )
                )
                db.execute(
                    insert(jobs).values(
                        id=event_id,
                        kind=kind,
                        payload=payload,
                        status="pending",
                        available_at=self.clock(),
                        lease_until=0,
                        attempts=0,
                    )
                )
            return True
        except IntegrityError:
            return False

    def claim(self):
        now = self.clock()
        with self.engine.begin() as db:
            # A crashed Slack send is ambiguous. Never blindly replay it.
            db.execute(
                update(jobs)
                .where(
                    jobs.c.kind == "slack",
                    jobs.c.status == "running",
                    jobs.c.lease_until <= now,
                )
                .values(status="uncertain", error="worker_interrupted")
            )
            eligible = ((jobs.c.status == "pending") & (jobs.c.available_at <= now)) | (
                (jobs.c.status == "running")
                & (jobs.c.lease_until <= now)
                & (jobs.c.kind != "slack")
            )
            candidates = (
                db.execute(
                    select(jobs).where(eligible).order_by(jobs.c.available_at).limit(10)
                )
                .mappings()
                .all()
            )
            for row in candidates:
                claimed = db.execute(
                    update(jobs)
                    .where(
                        jobs.c.id == row["id"],
                        jobs.c.status == row["status"],
                        jobs.c.attempts == row["attempts"],
                    )
                    .values(
                        status="running",
                        lease_until=now + 600,
                        attempts=row["attempts"] + 1,
                    )
                )
                if claimed.rowcount:
                    return dict(row, attempts=row["attempts"] + 1)
        return None

    def finish_job(self, key, *, status="done", delay=0, receipt=None, error=None):
        with self.engine.begin() as db:
            db.execute(
                update(jobs)
                .where(jobs.c.id == key)
                .values(
                    status=status,
                    available_at=self.clock() + delay,
                    lease_until=0,
                    receipt=receipt,
                    error=error,
                )
            )

    def job(self, key):
        with self.engine.connect() as db:
            row = db.execute(select(jobs).where(jobs.c.id == key)).mappings().first()
            return dict(row) if row else None

    def pending_jobs(self):
        with self.engine.connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    select(
                        jobs.c.id,
                        jobs.c.kind,
                        jobs.c.status,
                        jobs.c.attempts,
                        jobs.c.error,
                    ).where(
                        jobs.c.status.in_(["pending", "running", "failed", "uncertain"])
                    )
                ).mappings()
            ]

    def retry_job(self, key):
        with self.engine.begin() as db:
            result = db.execute(
                update(jobs)
                .where(jobs.c.id == key, jobs.c.status == "failed")
                .values(
                    status="pending", available_at=self.clock(), attempts=0, error=None
                )
            )
            if not result.rowcount:
                raise ValueError(
                    "Solo se reintentan tareas fallidas; un envío incierto requiere conciliación."
                )

    def notification(self, case_id, revision, status, manager_id):
        # Persist the visible artifact and its notification request atomically.
        key = f"notice:{case_id}:{revision}:{status}"
        payload = {
            "case_id": case_id,
            "revision": revision,
            "status": status,
            "manager_id": manager_id,
        }
        try:
            with self.engine.begin() as db:
                self.put_in(db, f"status:{case_id}", "status", payload)
                db.execute(
                    insert(jobs).values(
                        id=key,
                        kind="slack",
                        payload=payload,
                        status="pending",
                        available_at=self.clock(),
                        lease_until=0,
                        attempts=0,
                    )
                )
        except IntegrityError:
            pass

    @contextmanager
    def lock(self, key):
        owner = uuid.uuid4().hex
        now = self.clock()
        try:
            with self.engine.begin() as db:
                db.execute(
                    delete(leases).where(leases.c.key == key, leases.c.until < now)
                )
                db.execute(insert(leases).values(key=key, owner=owner, until=now + 600))
        except IntegrityError:
            raise Busy(
                "El expediente se está procesando; reintentar después."
            ) from None
        try:
            yield
        finally:
            with self.engine.begin() as db:
                db.execute(
                    delete(leases).where(leases.c.key == key, leases.c.owner == owner)
                )

    def start_work(self, case_id, phase, actor, actor_type, issue_url=None):
        session_id = uuid.uuid4().hex
        with self.engine.begin() as db:
            db.execute(
                insert(sessions).values(
                    id=session_id,
                    case_id=case_id,
                    phase=phase,
                    actor=actor,
                    actor_type=actor_type,
                    issue_url=issue_url,
                    started_at=self.clock(),
                )
            )
        return session_id

    def stop_work(self, session_id, actor):
        with self.engine.begin() as db:
            result = db.execute(
                update(sessions)
                .where(
                    sessions.c.id == session_id,
                    sessions.c.actor == actor,
                    sessions.c.ended_at.is_(None),
                )
                .values(ended_at=self.clock())
            )
            if not result.rowcount:
                raise ValueError("Sesión inexistente, cerrada o de otro responsable.")

    def pause_human_work(self, case_id, actor):
        with self.engine.begin() as db:
            db.execute(
                update(sessions)
                .where(
                    sessions.c.case_id == case_id,
                    sessions.c.actor == actor,
                    sessions.c.actor_type == "human",
                    sessions.c.ended_at.is_(None),
                )
                .values(ended_at=self.clock())
            )

    def record_calendar_work(self, key, case_id, start, end, manager_id):
        if not 0 <= end - start <= 3600:
            raise ValueError("Intervalo de agenda inválido.")
        phase_key = f"phase:{case_id}:calendar-tools"
        try:
            with self.engine.begin() as db:
                db.execute(
                    insert(sessions).values(
                        id=key[:64],
                        case_id=case_id,
                        phase="calendar-tools",
                        actor="calendar-assistant",
                        actor_type="agent",
                        started_at=start,
                        ended_at=end,
                    )
                )
                previous = db.execute(
                    select(records.c.payload).where(records.c.key == phase_key)
                ).scalar()
                self.put_in(
                    db,
                    phase_key,
                    "phase",
                    {
                        "case_id": case_id,
                        "phase": "calendar-tools",
                        "accepted_at": min(start, previous["accepted_at"])
                        if previous
                        else start,
                        "completed_at": max(end, previous["completed_at"])
                        if previous
                        else end,
                        "manager_id": manager_id,
                        "issue_url": "",
                        "coverage": "calendar_tool_execution_only",
                    },
                )
        except IntegrityError:
            pass

    @contextmanager
    def work(self, case_id, phase, actor="preparation-agent"):
        session_id = self.start_work(case_id, phase, actor, "agent")
        try:
            yield
        finally:
            self.stop_work(session_id, actor)

    def phase(self, case_id, phase, manager_id, issue_url=""):
        key = f"phase:{case_id}:{phase}"
        current = self.get(key)
        if current:
            return current
        payload = {
            "case_id": case_id,
            "phase": phase,
            "accepted_at": self.clock(),
            "completed_at": None,
            "manager_id": manager_id,
            "issue_url": issue_url,
        }
        self.put(key, "phase", payload)
        return payload

    def complete_phase(self, case_id, phase):
        key = f"phase:{case_id}:{phase}"
        current = self.get(key)
        if current and current["completed_at"] is None:
            self.put(key, "phase", dict(current, completed_at=self.clock()))

    def reopen_phase(self, case_id, phase):
        """Reopen a completed phase for traceable rework without changing its start."""
        key = f"phase:{case_id}:{phase}"
        current = self.get(key)
        if current and current["completed_at"] is not None:
            self.put(key, "phase", dict(current, completed_at=None))

    def stage_one_metrics(self, case_id, work):
        with self.engine.connect() as db:
            project = (
                db.execute(select(projects).where(projects.c.case_id == case_id))
                .mappings()
                .first()
            )
        if not project:
            return None
        transfers = self.case_handoffs(case_id)
        delivered = next(
            (
                h
                for h in transfers
                if h["to_phase"] == "stage-2" and h["accepted_at"] is not None
            ),
            None,
        )
        end = delivered["accepted_at"] if delivered else self.clock()
        closed = [
            s
            for s in work
            if s["ended_at"] is not None
            and s["started_at"] <= end
            and s["ended_at"] >= project["opened_at"]
        ]

        def union_seconds(intervals):
            total, last = 0.0, float("-inf")
            for start, stop in sorted(intervals):
                total += max(0, stop - max(start, last))
                last = max(last, stop)
            return total

        active = union_seconds(
            (max(project["opened_at"], s["started_at"]), min(end, s["ended_at"]))
            for s in closed
        )
        return {
            "opened_at": project["opened_at"],
            "completed_at": end if delivered else None,
            "lead_seconds": end - project["opened_at"],
            "process_union_seconds": active,
            "wait_or_unrecorded_seconds": max(0, end - project["opened_at"] - active),
            "effort_by_actor_seconds": {
                actor: union_seconds(
                    (
                        max(project["opened_at"], s["started_at"]),
                        min(end, s["ended_at"]),
                    )
                    for s in closed
                    if s["actor"] == actor
                )
                for actor in {s["actor"] for s in closed}
            },
            "coverage": "recorded intervals; parent/detail phases are unioned, not summed",
        }

    def metrics(self, case_id):
        with self.engine.connect() as db:
            work = [
                dict(row)
                for row in db.execute(
                    select(sessions).where(sessions.c.case_id == case_id)
                ).mappings()
            ]
        result = []
        for phase in self.list("phase"):
            if phase["case_id"] != case_id:
                continue
            intervals = [w for w in work if w["phase"] == phase["phase"]]
            end = phase["completed_at"] or self.clock()
            closed = [w for w in intervals if w["ended_at"] is not None]
            spans = sorted(
                (max(phase["accepted_at"], w["started_at"]), min(end, w["ended_at"]))
                for w in closed
            )
            union = 0.0
            last_end = phase["accepted_at"]
            for start, stop in spans:
                union += max(0, stop - max(start, last_end))
                last_end = max(last_end, stop)
            effort = {
                kind: sum(
                    w["ended_at"] - w["started_at"]
                    for w in closed
                    if w["actor_type"] == kind
                )
                for kind in ("human", "agent")
            }
            lead = end - phase["accepted_at"]
            result.append(
                {
                    **phase,
                    "lead_seconds": lead,
                    "in_progress": phase["completed_at"] is None,
                    "process_union_seconds": union,
                    "recorded_effort_seconds": effort,
                    "unrecorded_or_wait_seconds": max(0, lead - union),
                    "open_sessions": sum(w["ended_at"] is None for w in intervals),
                    "coverage": "recorded_intervals_only; no inferred activity from issues",
                }
            )
        with self.engine.connect() as db:
            history = [
                dict(row)
                for row in db.execute(
                    select(events).where(events.c.case_id == case_id)
                ).mappings()
            ]
        return {
            "case_id": case_id,
            "phases": result,
            "sessions": work,
            "rework_cycles": sum(
                bool(
                    e["kind"] == "approval.decided"
                    and e["payload"].get("decision") == "revise"
                    or e["payload"].get("requires_rework", False)
                    or e["kind"] == "architecture.finops_correction_requested"
                )
                for e in history
            ),
            "handoff": self.get(f"handoff:{case_id}"),
            "stage_1": self.stage_one_metrics(case_id, work),
            "handoffs": [
                {
                    **h,
                    "wait_seconds": (h["accepted_at"] or self.clock())
                    - h["created_at"],
                    "pending_acceptance": h["accepted_at"] is None,
                }
                for h in self.case_handoffs(case_id)
            ],
            "human_in_the_loop": [
                {"kind": e["kind"], "at": e["at"], **e["payload"]}
                for e in history
                if e["kind"] in {"approval.requested", "approval.decided"}
            ],
        }

    def import_references(self, root):
        manifest = json.loads((root / "provenance.json").read_text())
        for file in manifest["files"]:
            path = root.parent / file["path"]
            content = path.read_text(encoding="utf-8")
            digest = hashlib.sha256(content.encode()).hexdigest()
            if digest != file["sha256"]:
                raise ValueError("Una referencia cambió sin actualizar su procedencia.")
            self.put(
                f"reference:{file['path']}",
                "reference",
                {
                    "path": file["path"],
                    "content": content,
                    "sha256": digest,
                    "source_commit": manifest["commit"],
                    "is_fictitious": True,
                },
            )
