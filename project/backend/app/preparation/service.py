"""Single-process local application service shared by MCP and tests."""

import hashlib
import json
from contextlib import nullcontext
from datetime import datetime, timezone
from threading import RLock

from app.preparation.deliveries import PreparationDeliveries
from app.preparation.models import ExecutivePackage
from app.preparation.speaker_notes import presentation_digest
from app.preparation.state import (
    input_hash,
    meeting_documents,
    meeting_sources,
    utc_now,
)
from app.workflow.ports import WorkflowExecution


class PreparationService:
    def __init__(
        self,
        graph: WorkflowExecution,
        store=None,
        manager_id="engagement-manager",
        on_sync=None,
        direction_actor="executive-direction-agent",
        notifications=True,
    ):
        self.graph = graph
        self.store = store
        self.manager_id = manager_id
        self.lock = RLock()
        self.on_sync = on_sync
        self.direction_actor = direction_actor
        self.notifications = notifications

    def _owned(self, case_id):
        if self.store:
            owner = self.store.get(f"owner:{case_id}")
            if owner and owner["manager_id"] != self.manager_id:
                raise ValueError("Expediente de otro responsable.")

    def _sync(self, case_id):
        if not self.store:
            return
        state = self.get(case_id)["state"]
        if state.get("status") in {"awaiting_review", "ready_for_stage_2"}:
            if self.notifications:
                self.store.notification(
                    case_id, state["revision"], state["status"], self.manager_id
                )
            else:
                self.store.put(
                    f"status:{case_id}",
                    "status",
                    {
                        "case_id": case_id,
                        "revision": state["revision"],
                        "status": state["status"],
                        "manager_id": self.manager_id,
                    },
                )
        if state.get("status") == "awaiting_review":
            self.store.create_handoff(
                f"{case_id}:preparation:stuart:v{state['revision']}",
                case_id,
                "preparation-agent",
                self.manager_id,
                "preparation",
                "manager_review",
                revision=state["revision"],
                artifact_sha256=self._digest(state),
            )
            self.store.event(
                f"review-request:{case_id}:{state['revision']}",
                case_id,
                "approval.requested",
                {
                    "revision": state["revision"],
                    "actor": self.manager_id,
                    "subject": state.get("review_subject", "presentation"),
                },
            )
        if state.get("status") == "ready_for_stage_2":
            self.store.put(
                f"handoff:{case_id}",
                "handoff",
                {
                    **state["handoff"],
                    "case_id": case_id,
                    "manager_id": self.manager_id,
                    "approved_at": state["handed_off_at"],
                    "sha256": hashlib.sha256(
                        json.dumps(
                            state.get("package", state["draft"]), sort_keys=True
                        ).encode()
                    ).hexdigest(),
                    "receipt": "awaiting_stage_2_acceptance",
                },
            )
            self.store.complete_phase(case_id, "preparation")
            self.store.create_handoff(
                f"{case_id}:stage-1:stage-2:v{state['revision']}",
                case_id,
                self.manager_id,
                self.direction_actor,
                "preparation",
                "stage-2",
                revision=state["revision"],
                artifact_sha256=self._digest(state),
            )
            receipt = self.store.handoff(
                f"{case_id}:stage-1:stage-2:v{state['revision']}"
            )
            if receipt["accepted_at"] is not None:
                legacy = self.store.get(f"handoff:{case_id}")
                self.store.put(
                    f"handoff:{case_id}",
                    "handoff",
                    {
                        **legacy,
                        "receipt": "accepted_by_stage_2",
                        "accepted_at": receipt["accepted_at"],
                        "accepted_by": receipt["accepted_by"],
                    },
                )

        if self.on_sync and state.get("status") in {
            "awaiting_review",
            "ready_for_stage_2",
        }:
            self.on_sync(case_id, state)

    @staticmethod
    def _digest(state):
        return hashlib.sha256(
            json.dumps(state.get("package", state["draft"]), sort_keys=True).encode()
        ).hexdigest()

    @staticmethod
    def thread_id(case_id):
        if not case_id or len(case_id) > 120:
            raise ValueError("case_id debe tener entre 1 y 120 caracteres.")
        return f"preparation:{case_id}"

    def get(self, case_id):
        with self.lock:
            self._owned(case_id)
            snapshot = self.graph.inspect(self.thread_id(case_id))
            if not snapshot.state:
                raise ValueError("Expediente inexistente.")
            pending = snapshot.pending
            return {"state": snapshot.state, "pending": pending}

    def checkpoint_id(self, case_id):
        self._owned(case_id)
        return self.graph.inspect(self.thread_id(case_id)).checkpoint_id

    def wait_for_meeting(self, case_id, calendar_event_id):
        with self.lock, self.store.lock(f"case:{case_id}"):
            self._owned(case_id)
            config = self.thread_id(case_id)
            if not self.graph.inspect(config).state:
                self.graph.start(
                    config,
                    {
                        "case_id": case_id,
                        "calendar_event_id": calendar_event_id,
                        "status": "awaiting_meeting",
                    },
                )
            return self.get(case_id)

    def cancel_waiting_meeting(self, case_id):
        with self.lock, self.store.lock(f"case:{case_id}"):
            snapshot = self.graph.inspect(self.thread_id(case_id))
            if snapshot.state.get("status") == "awaiting_meeting":
                self.graph.resume(self.thread_id(case_id), {"cancelled": True})

    def start(self, case_id, event_id, transcript, query, meeting_notes=""):
        if not event_id.strip() or not transcript.strip() or not query.strip():
            raise ValueError("Indicar evento, transcripción y consulta de referencias.")
        with (
            self.lock,
            self.store.lock(f"case:{case_id}") if self.store else nullcontext(),
        ):
            self._owned(case_id)
            config = self.thread_id(case_id)
            previous = self.graph.inspect(config).state
            if previous.get("status") == "meeting_cancelled":
                raise ValueError("La reunión fue cancelada.")
            if self.store:
                self.store.put(
                    f"owner:{case_id}",
                    "owner",
                    {"case_id": case_id, "manager_id": self.manager_id},
                )
                self.store.phase(case_id, "preparation", self.manager_id)
            fingerprint = input_hash(transcript, query, meeting_notes)
            if previous:
                if previous.get("status") == "awaiting_meeting":
                    self._receive_transcript(case_id, transcript)
                    self.graph.resume(
                        config,
                        {
                            "event_id": event_id,
                            "transcript": transcript,
                            "meeting_notes": meeting_notes,
                            "query": query,
                            "input_hash": fingerprint,
                            "accepted_at": datetime.fromtimestamp(
                                self.store.clock(), timezone.utc
                            ).isoformat(),
                        },
                    )
                    self._sync(case_id)
                    self._accept_transcript(case_id)
                    return self.get(case_id)
                if (
                    previous["event_id"] != event_id
                    or previous["input_hash"] != fingerprint
                ):
                    raise ValueError(
                        "El expediente ya tiene otra entrada; conciliar primero."
                    )
                snapshot = self.graph.inspect(config)
                if snapshot.runnable:
                    # Retry a failed node from its durable checkpoint.
                    self.graph.continue_run(config)
                self._sync(case_id)
                self._accept_transcript(case_id)
                return self.get(case_id)
            self._receive_transcript(case_id, transcript)
            self.graph.start(
                config,
                {
                    "case_id": case_id,
                    "event_id": event_id,
                    "input_hash": fingerprint,
                    "transcript": transcript,
                    "meeting_notes": meeting_notes,
                    "query": query,
                    "accepted_at": datetime.fromtimestamp(
                        self.store.clock(), timezone.utc
                    ).isoformat()
                    if self.store
                    else utc_now(),
                },
            )
            self._sync(case_id)
            self._accept_transcript(case_id)
            return self.get(case_id)

    def _receive_transcript(self, case_id, transcript):
        if not self.store:
            return
        handoff_id = f"{case_id}:meeting:preparation"
        if not self.store.handoff(handoff_id):
            self.store.create_handoff(
                handoff_id,
                case_id,
                self.manager_id,
                "preparation-agent",
                "transcript_intake",
                "preparation",
                revision=1,
                artifact_sha256=hashlib.sha256(transcript.encode()).hexdigest(),
            )

    def _accept_transcript(self, case_id):
        if self.store and self.store.handoff(f"{case_id}:meeting:preparation"):
            self.store.accept_handoff(
                f"{case_id}:meeting:preparation", "preparation-agent"
            )

    def resume(self, case_id, action, value, expected_revision=None):
        with (
            self.lock,
            self.store.lock(f"case:{case_id}") if self.store else nullcontext(),
        ):
            current = self.get(case_id)
            if (
                expected_revision is not None
                and current["state"].get("revision") != expected_revision
            ):
                raise ValueError("La revisión cambió; consultar el borrador actual.")
            if not current["pending"] or current["pending"][0]["action"] != action:
                raise ValueError("La acción no corresponde al estado actual.")
            if self.store and action == "manager_review":
                if not isinstance(value, dict) or value.get("decision") not in {
                    "approve",
                    "revise",
                }:
                    raise ValueError("Decisión inválida.")
                if (
                    value["decision"] == "revise"
                    and not value.get("feedback", "").strip()
                ):
                    raise ValueError("Indicar los ajustes solicitados.")
                state = current["state"]
                if value["decision"] == "approve":
                    package = ExecutivePackage.model_validate(state.get("package", {}))
                    if not package.presentation or any(
                        not slide.title.strip() for slide in package.presentation
                    ):
                        raise ValueError(
                            "La aprobación requiere una presentación estructurada."
                        )
                    if (
                        state.get("review_subject") == "speaker_notes"
                        and not package.speaker_notes.strip()
                    ):
                        raise ValueError("El guion no puede estar vacío.")
                    if state.get("review_subject", "presentation") == "presentation":
                        PreparationDeliveries(self.store).presentation_files(
                            case_id, state["revision"], state["package"]
                        )
                digest = hashlib.sha256(
                    json.dumps(
                        state.get("package", state["draft"]), sort_keys=True
                    ).encode()
                ).hexdigest()
                self.store.event(
                    f"review:{case_id}:{state['revision']}",
                    case_id,
                    "approval.decided",
                    {
                        "actor": self.manager_id,
                        "decision": value["decision"],
                        "revision": state["revision"],
                        "artifact_sha256": digest,
                        "feedback": value.get("feedback", ""),
                        "subject": state.get("review_subject", "presentation"),
                    },
                )
                self.store.pause_human_work(case_id, self.manager_id)
                if self.on_sync and value["decision"] == "revise":
                    self.on_sync(case_id, {**state, "status": "awaiting_draft"})
            self.graph.resume(self.thread_id(case_id), value)
            self._sync(case_id)
            return self.get(case_id)

    def review(self, case_id, revision, decision, feedback=""):
        if decision not in {"approve", "revise"} or (
            decision == "revise" and not feedback.strip()
        ):
            raise ValueError("Indicar approve o revise y los ajustes solicitados.")
        with self.lock:
            state = self.get(case_id)["state"]
            if revision != state.get("revision"):
                raise ValueError(
                    "La revisión cambió; consultar el borrador actual antes de decidir."
                )
            result = self.resume(
                case_id,
                "manager_review",
                {"decision": decision, "feedback": feedback},
                revision,
            )
            return result

    def continue_preparation(self, case_id):
        state = self.get(case_id)["state"]
        if state.get("status") in {"awaiting_meeting", "meeting_cancelled"}:
            return self.get(case_id)
        return self.start(
            case_id,
            state["event_id"],
            state["transcript"],
            state["query"],
            state.get("meeting_notes", ""),
        )

    def begin_review(self, case_id, revision):
        with self.lock, self.store.lock(f"case:{case_id}"):
            state = self.get(case_id)["state"]
            if (
                state.get("status") != "awaiting_review"
                or state.get("revision") != revision
            ):
                raise ValueError("Seleccionar la revisión pendiente actual.")
            handoff = self.store.accept_handoff(
                f"{case_id}:preparation:stuart:v{revision}", self.manager_id
            )
            active = [
                s
                for s in self.store.metrics(case_id)["sessions"]
                if s["actor"] == self.manager_id and s["ended_at"] is None
            ]
            session_id = (
                active[0]["id"]
                if active
                else self.store.start_work(
                    case_id, "preparation", self.manager_id, "human"
                )
            )
        return {
            "status": "working",
            "session_id": session_id,
            "revision": revision,
            "handoff": handoff,
        }

    def comment(self, case_id, revision, text):
        with self.lock, self.store.lock(f"case:{case_id}"):
            state = self.get(case_id)["state"]
            if state["revision"] != revision:
                raise ValueError("La revisión cambió; leer los insumos actuales.")
            note = self.store.add_note(case_id, revision, self.manager_id, text)
            return {"status": "saved", "note_id": note, "revision": revision}

    def update_package(self, case_id, revision, changes, comment=""):
        with self.lock, self.store.lock(f"case:{case_id}"):
            state = self.get(case_id)["state"]
            if (
                state.get("status") != "awaiting_review"
                or state.get("revision") != revision
            ):
                raise ValueError("La revisión cambió o ya fue aprobada.")
            if not changes or not set(changes) <= set(ExecutivePackage.model_fields):
                raise ValueError("Indicar secciones válidas para cambiar.")
            script_only = set(changes) == {"speaker_notes"}
            if script_only and state.get("review_subject") != "speaker_notes":
                raise ValueError(
                    "El guion se genera después de aprobar la presentación."
                )
            if script_only and not str(changes["speaker_notes"]).strip():
                raise ValueError("El guion no puede estar vacío.")
            sources = meeting_sources(state)
            sources.update(
                {d["path"]: d["content"] for d in self.store.list("reference")}
            )
            project_ids = {
                p.split("/")[2] for p in sources if p.startswith("references/projects/")
            }
            package = ExecutivePackage.model_validate({**state["package"], **changes})
            package.validate_sources(sources, project_ids)
            if package.model_dump() == state["package"]:
                return self.get(case_id)
            if not script_only:
                package = package.model_copy(update={"speaker_notes": ""})
            approval = state.get("presentation_approval", {}) if script_only else {}
            if script_only and approval.get(
                "presentation_sha256"
            ) != presentation_digest(package.model_dump()):
                raise ValueError("La presentación requiere nueva aprobación.")
            new_revision = revision + 1
            documents = {
                **meeting_documents(state),
                **package.artifacts(),
            }
            self.store.put(
                f"artifact:{case_id}:{new_revision}",
                "artifact",
                {
                    "case_id": case_id,
                    "revision": new_revision,
                    "package": package.model_dump(),
                    "documents": documents,
                    "presentation_approval": approval,
                },
            )
            self.graph.update(
                self.thread_id(case_id),
                {
                    "package": package.model_dump(),
                    "draft": documents["executive-summary.md"],
                    "revision": new_revision,
                    "status": "awaiting_review",
                    "decision": "",
                    "review_subject": "speaker_notes"
                    if script_only
                    else "presentation",
                    "presentation_approval": approval,
                },
                after_step="draft",
            )
            self.graph.continue_run(self.thread_id(case_id))
            self.store.add_note(
                case_id,
                new_revision,
                self.manager_id,
                comment or "Insumos editados durante la revisión conjunta.",
            )
            self.store.event(
                f"edit:{case_id}:{new_revision}",
                case_id,
                "artifact.revised",
                {
                    "actor": self.manager_id,
                    "from_revision": revision,
                    "revision": new_revision,
                    "sections": sorted(changes),
                },
            )
            self._sync(case_id)
            return self.get(case_id)

    def metrics(self, case_id):
        if self.store:
            self._owned(case_id)
            return self.store.metrics(case_id)
        state = self.get(case_id)["state"]
        end = state.get("handed_off_at")
        lead = (
            (
                datetime.fromisoformat(end)
                - datetime.fromisoformat(state["accepted_at"])
            ).total_seconds()
            if end
            else None
        )
        return {
            "scope": "post_meeting_preparation_only",
            "accepted_at": state["accepted_at"],
            "handed_off_at": end,
            "lead_seconds": lead,
            "measured_agent_process_seconds": state.get("search_seconds"),
            "human_process_seconds": None,
            "drafting_process_seconds": None,
            "rework_revisions": max(0, state.get("revision", 0) - 1),
            "coverage": "partial: retrieval only; no inferred human or drafting time",
        }
