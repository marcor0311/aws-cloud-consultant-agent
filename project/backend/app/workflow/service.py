"""Shared application service for queued HTTP/MCP events and worker execution."""

import hashlib
import json

from app.workflow.ports import WorkflowExecution
from app.workflow.state import OPERATOR_EVENTS, initial_state
from app.workflow.transitions import fingerprint, transition


class ProcessService:
    def __init__(self, graph: WorkflowExecution, store, manager_id):
        self.graph, self.store, self.manager_id = graph, store, manager_id

    @staticmethod
    def thread_id(case_id):
        if not isinstance(case_id, str) or not 1 <= len(case_id) <= 120:
            raise ValueError("Expediente inválido.")
        return f"process:{case_id}"

    def _owned(self, case_id):
        owner = self.store.get(f"owner:{case_id}")
        if not owner or owner["manager_id"] != self.manager_id:
            raise ValueError("Expediente inexistente o de otro responsable.")

    def accept_stage(self, case_id, stage, issue_url=""):
        self._owned(case_id)
        if not 1 <= stage <= 6:
            raise ValueError("La etapa debe estar entre 1 y 6.")
        return self.store.phase(case_id, f"stage-{stage}", self.manager_id, issue_url)

    def start_work(self, case_id, stage="preparation", issue_url=""):
        self._owned(case_id)
        if stage not in {"preparation", *(f"stage-{n}" for n in range(1, 7))}:
            raise ValueError("Etapa inválida.")
        self.store.phase(case_id, stage, self.manager_id, issue_url)
        session = self.store.start_work(
            case_id, stage, self.manager_id, "human", issue_url
        )
        return {"session_id": session, "status": "active"}

    def pause_work(self, session_id):
        self.store.stop_work(session_id, self.manager_id)
        return {"status": "paused"}

    def accept_delivery(self, handoff_id):
        return self.store.accept_handoff(handoff_id, self.manager_id)

    def observe_github(
        self, delivery, issue_url, kind, action, created_at, closed_at, requires_rework
    ):
        phases = [
            p for p in self.store.list("phase") if p.get("issue_url") == issue_url
        ]
        for phase in phases:
            self.store.event(
                f"github:{delivery}:{phase['case_id']}",
                phase["case_id"],
                "github.observed",
                {
                    "issue_url": issue_url,
                    "event": kind,
                    "action": action,
                    "created_at": created_at,
                    "closed_at": closed_at,
                    "requires_rework": requires_rework,
                },
            )
        # Source events provide evidence; they never approve a stage or infer human work.
        return {"status": "accepted", "linked_phases": len(phases)}

    def get(self, case_id):
        self._owned(case_id)
        snapshot = self.graph.inspect(self.thread_id(case_id))
        if not snapshot.state:
            raise ValueError("El expediente todavía no tiene un proceso confirmado.")
        return {
            "state": snapshot.state,
            "pending": snapshot.pending,
        }

    def ensure(self, case_id, client_id=None):
        self._owned(case_id)
        with self.store.lock(f"process:{case_id}"):
            config = self.thread_id(case_id)
            if not self.graph.inspect(config).state:
                self.graph.start(
                    config, initial_state(case_id, self.manager_id, client_id)
                )
            self._settle(case_id)
            result = self.get(case_id)
            self._sync(result["state"])
            return result

    def submit(self, case_id, payload):
        """Only an authenticated operator calls this entry point; no claimed actor."""
        if payload["kind"] not in OPERATOR_EVENTS:
            raise ValueError("Este evento solo puede emitirlo una integración interna.")
        event = {**payload, "actor": self.manager_id, "origin": "operator"}
        with self.store.lock(f"process:{case_id}"):
            state = self.get(case_id)["state"]
            if self._replayed(state, event):
                return {"status": "duplicate", "event_id": event["event_id"]}
            transition(state, event)
            key = self.job_key(case_id, event["event_id"])
            existing = self.store.job(key)
            if existing:
                if fingerprint(existing["payload"]["event"]) != fingerprint(event):
                    raise ValueError("El ID de evento ya tiene otro contenido.")
                return {"status": existing["status"], "task_id": key}
            self.store.receive(
                key, "process_event", {"case_id": case_id, "event": event}
            )
            return {"status": "pending", "task_id": key}

    @staticmethod
    def job_key(case_id, event_id):
        digest = hashlib.sha256(json.dumps([case_id, event_id]).encode()).hexdigest()
        return f"process-event:{digest}"

    @staticmethod
    def _replayed(state, event):
        previous = state["processed"].get(event["event_id"])
        if previous and previous != fingerprint(event):
            raise ValueError("El ID de evento ya tiene otro contenido.")
        return bool(previous)

    def apply(self, case_id, event):
        """Worker-side validation prevents stale queued decisions and replay."""
        with self.store.lock(f"process:{case_id}"):
            self._settle(case_id)
            state = self.get(case_id)["state"]
            if not self._replayed(state, event):
                event = {**event, "at": self.store.clock()}
                transition(state, event)
                self.graph.resume(self.thread_id(case_id), event)
            result = self.get(case_id)
            self._sync(result["state"])
            return result

    def _settle(self, case_id):
        snapshot = self.graph.inspect(self.thread_id(case_id))
        if snapshot.runnable:
            # Recovery after the event checkpoint committed, before the next pause.
            self.graph.continue_run(self.thread_id(case_id))

    def internal(self, case_id, event_id, kind, **data):
        state = self.get(case_id)["state"]
        # Internal identities remain stable across retries after a stage transition.
        previous = next(
            (e for e in state["history"] if e["event_id"] == event_id), None
        )
        event = {
            "event_id": event_id,
            "kind": kind,
            "stage": previous["stage"] if previous else state["stage"],
            "iteration": previous["iteration"] if previous else state["iteration"],
            "actor": self.manager_id if kind == "preparation.approved" else "workflow",
            "origin": "internal",
            **data,
        }
        return self.apply(case_id, event)

    def sync_preparation(self, case_id, state):
        if not self.graph.inspect(self.thread_id(case_id)).state:
            # Existing/manual preparation checkpoints are kept intact; no invented meeting.
            return
        kind = (
            "preparation.approved"
            if state["status"] == "ready_for_stage_2"
            else (
                "preparation.revision_requested"
                if state["status"] == "awaiting_draft"
                else "preparation.ready"
            )
        )
        digest = hashlib.sha256(
            json.dumps(state.get("package", state["draft"]), sort_keys=True).encode()
        ).hexdigest()
        data = dict(
            revision=state["revision"],
            artifact_sha256=digest,
            evidence=[f"artifact:{case_id}:{state['revision']}"],
        )
        if kind == "preparation.approved":
            # Also recover an approved legacy preparation after its meeting is reconciled.
            self.internal(
                case_id,
                f"preparation.ready:{state['revision']}:{digest}",
                "preparation.ready",
                **data,
            )
        self.internal(case_id, f"{kind}:{state['revision']}:{digest}", kind, **data)

    def _sync(self, state):
        # Rebuild idempotent SQL projections if a crash happened after the checkpoint.
        case_id = state["case_id"]
        self.store.put(
            f"process:{case_id}",
            "process",
            {
                k: state[k]
                for k in (
                    "case_id",
                    "client_id",
                    "stage",
                    "iteration",
                    "status",
                    "revision",
                    "artifact_sha256",
                    "rework_cycles",
                )
            },
        )
        for event in state["history"]:
            self.store.event(
                self.job_key(case_id, event["event_id"]) + ":applied",
                case_id,
                "process.transition",
                event,
            )
            if (
                event["to_iteration"] != event["from_iteration"]
                and event["from_stage"] > 1
            ):
                self.store.create_handoff(
                    f"{case_id}:process:{event['from_iteration']}:{event['to_iteration']}",
                    case_id,
                    event["actor"],
                    self.manager_id,
                    f"stage-{event['from_stage']}",
                    f"stage-{event['to_stage']}",
                    revision=event.get("revision", 0),
                    artifact_sha256=event.get("artifact_sha256"),
                )
