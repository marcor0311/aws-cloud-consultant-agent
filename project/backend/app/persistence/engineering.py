"""Engineering receipts, files and measured intervals in the existing workflow SQL."""

import base64
from uuid import uuid5

from sqlalchemy import insert, update

from app.persistence.delivery import DeliveryConflict
from app.persistence.workflow import events, handoffs, jobs, sessions


class EngineeringRepository:
    def __init__(self, store):
        self.store = store

    def get(self, intake_id):
        return self.store.get(f"engineering:{intake_id}")

    def evidence(self, run_id):
        return self.store.get(f"engineering-evidence:{run_id}")

    def runs(self, intake_id):
        return sorted(
            [
                r
                for r in self.store.list("engineering-evidence")
                if r["intake_id"] == str(intake_id)
            ],
            key=lambda r: (r["recorded_at"], r["run_id"]),
        )

    def _files(self, db, intake_id, files):
        refs = []
        for ref, data in files:
            key = f"engineering-file:{intake_id}:{ref['sha256']}"
            self.store.put_in(
                db,
                key,
                "engineering-file",
                {
                    "content_base64": base64.b64encode(data).decode(),
                    "sha256": ref["sha256"],
                },
            )
            refs.append(ref)
        return refs

    def register(self, request, input_sha256, operator, files, project, handoff):
        now = self.store.clock()
        received = handoff["accepted_at"] if handoff["accepted_at"] is not None else now
        record = {
            "intake_id": str(request.intake_id),
            "case_id": request.case_id,
            "input_sha256": input_sha256,
            "operator": operator,
            "project_id": project["project_id"],
            "is_fictitious": bool(project["is_fictitious"]),
            "received_at": received,
            "recorded_at": now,
            "process_iteration": self.store.get(f"process:{request.case_id}")[
                "iteration"
            ],
            "input": request.model_dump(mode="json"),
            "approval_validation": "matched_workflow_decisions",
            "baseline_approval_validation": "external_references_declared",
            "status": "inputs_recorded",
        }
        with self.store.engine.begin() as db:
            record["files"] = self._files(db, request.intake_id, files)
            if handoff["accepted_at"] is None:
                db.execute(
                    update(handoffs)
                    .where(
                        handoffs.c.id == handoff["id"], handoffs.c.accepted_at.is_(None)
                    )
                    .values(accepted_at=now, accepted_by=operator)
                )
                db.execute(
                    insert(events).values(
                        id=f"engineering-accepted:{request.intake_id}",
                        case_id=request.case_id,
                        kind="handoff.accepted",
                        at=now,
                        payload={"handoff_id": handoff["id"], "actor": operator},
                    )
                )
            phase_key = f"phase:{request.case_id}:stage-5"
            existing = self.store.get(phase_key)
            if existing and (
                existing["accepted_at"] > received
                or existing["completed_at"] is not None
            ):
                raise DeliveryConflict(
                    "La fase de ingeniería no admite los intervalos de esta recepción"
                )
            if not existing:
                self.store.put_in(
                    db,
                    phase_key,
                    "phase",
                    {
                        "case_id": request.case_id,
                        "phase": "stage-5",
                        "accepted_at": received,
                        "completed_at": None,
                        "manager_id": operator,
                        "issue_url": "",
                    },
                )
            self.store.put_in(
                db, f"engineering:{request.intake_id}", "engineering", record
            )
            db.execute(
                insert(events).values(
                    id=f"engineering-input:{request.intake_id}",
                    case_id=request.case_id,
                    kind="engineering.inputs_recorded",
                    at=now,
                    payload={
                        "intake_id": str(request.intake_id),
                        "input_sha256": input_sha256,
                        "actor": operator,
                    },
                )
            )
        return record

    def record(self, intake, evidence, evidence_sha256, operator, files):
        now = self.store.clock()
        value = evidence.model_dump(mode="json")
        record = {
            "case_id": intake["case_id"],
            "intake_id": intake["intake_id"],
            "run_id": str(evidence.run_id),
            "input_sha256": intake["input_sha256"],
            "evidence_sha256": evidence_sha256,
            "operator": operator,
            "recorded_at": now,
            "evidence": value,
            "execution_verification": "operator_recorded; files_hash_verified; execution_not_authenticated",
            "intervals": [],
            "reported_status": "passed"
            if all(c.status == "passed" for c in evidence.checks)
            else (
                "failed"
                if any(c.status == "failed" for c in evidence.checks)
                else "incomplete"
            ),
        }
        with self.store.engine.begin() as db:
            record["files"] = self._files(db, evidence.intake_id, files)
            for check in evidence.checks:
                if check.status == "not_run":
                    continue
                session_id = uuid5(evidence.run_id, check.name).hex
                start, end = check.started_at.timestamp(), check.ended_at.timestamp()
                # One measured interval per operation. Do not add a parent run interval.
                db.execute(
                    insert(sessions).values(
                        id=session_id,
                        case_id=intake["case_id"],
                        phase="stage-5",
                        actor=evidence.actor,
                        actor_type="agent",
                        issue_url=evidence.run_reference,
                        started_at=start,
                        ended_at=end,
                    )
                )
                record["intervals"].append(
                    {
                        "session_id": session_id,
                        "kind": check.kind,
                        "source": f"engineering-evidence:{evidence.run_id}",
                    }
                )
            self.store.put_in(
                db,
                f"engineering-evidence:{evidence.run_id}",
                "engineering-evidence",
                record,
            )
            db.execute(
                insert(events).values(
                    id=f"engineering-evidence:{evidence.run_id}",
                    case_id=intake["case_id"],
                    kind="engineering.evidence_recorded",
                    at=now,
                    payload={
                        "run_id": str(evidence.run_id),
                        "intake_id": intake["intake_id"],
                        "evidence_sha256": evidence_sha256,
                        "actor": operator,
                    },
                )
            )
        return record

    def file(self, intake_id, sha256):
        return self.store.get(f"engineering-file:{intake_id}:{sha256}")

    def release(self, intake_id):
        return self.store.get(f"engineering-release:{intake_id}")

    def record_release(self, intake, release, operator, catalog):
        verified = self.store.get(f"engineering-integration:{intake['intake_id']}")
        record = {
            "intake_id": intake["intake_id"],
            "case_id": intake["case_id"],
            "operator": operator,
            "recorded_at": self.store.clock(),
            "release": release.model_dump(mode="json"),
            "release_sha256": release.approval_digest(),
            "catalog": catalog,
            "verification": "workflow_approval_matched; github_and_baselines_operator_attested",
        }
        if verified and verified["release"] == record["release"]:
            record["external_verification"] = verified
            record["verification"] = verified["verification"]
        with self.store.engine.begin() as db:
            self.store.put_in(
                db,
                f"engineering-release:{intake['intake_id']}",
                "engineering-release",
                record,
            )
            db.execute(
                insert(events).values(
                    id=f"engineering-release:{intake['intake_id']}",
                    case_id=intake["case_id"],
                    kind="engineering.delivery_available",
                    at=record["recorded_at"],
                    payload={
                        "intake_id": intake["intake_id"],
                        "release_sha256": record["release_sha256"],
                        "actor": operator,
                        "to_phase": "stage-6",
                    },
                )
            )
            db.execute(
                insert(jobs).values(
                    id=f"engineering-notice:{intake['intake_id']}",
                    kind="slack",
                    payload={
                        "topic": "engineering",
                        "case_id": intake["case_id"],
                        "intake_id": intake["intake_id"],
                        "revision": release.revision,
                        "release_sha256": record["release_sha256"],
                        "status": "engineering_ready",
                        "manager_id": operator,
                        "pull_request": release.pull_request,
                    },
                    status="pending",
                    available_at=record["recorded_at"],
                    lease_until=0,
                    attempts=0,
                )
            )
        return record
