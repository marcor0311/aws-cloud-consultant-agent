"""Application service for architecture revisions and handoff to FinOps."""

import hashlib
import json
from contextlib import nullcontext
from threading import RLock

from app.architecture.models import ArchitecturePackage


class ArchitectureService:
    def __init__(
        self, graph, catalog, store=None, process=None, architect_id="architect"
    ):
        self.graph, self.catalog, self.store = graph, catalog, store
        self.process, self.architect_id = process, architect_id
        self.lock = RLock()

    @staticmethod
    def thread_id(case_id):
        if not isinstance(case_id, str) or not 1 <= len(case_id) <= 120:
            raise ValueError("Expediente inválido.")
        return f"architecture:{case_id}"

    @staticmethod
    def digest(package):
        return hashlib.sha256(
            json.dumps(package, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def get(self, case_id):
        snapshot = self.graph.inspect(self.thread_id(case_id))
        if not snapshot.state:
            raise ValueError("El expediente no tiene un diseño de arquitectura.")
        return {"state": snapshot.state, "pending": snapshot.pending}

    def catalog_modules(self):
        return self.catalog.modules()

    def start(self, case_id, input_id, package):
        validated = ArchitecturePackage.model_validate(package)
        payload = validated.model_dump(mode="json")
        fingerprint = self.digest(payload)
        guard = (
            self.store.lock(f"architecture:{case_id}") if self.store else nullcontext()
        )
        with self.lock, guard:
            previous = self.graph.inspect(self.thread_id(case_id)).state
            if previous:
                if (
                    previous.get("input_id") != input_id
                    or previous.get("input_hash") != fingerprint
                ):
                    raise ValueError(
                        "El expediente ya tiene otra entrada de arquitectura."
                    )
                return self.get(case_id)
            if self.process:
                process = self.process.get(case_id)["state"]
                if process["stage"] != 3 or process["status"] != "awaiting_deliverable":
                    raise ValueError(
                        "El proceso no está esperando el diseño de arquitectura."
                    )
            self.graph.start(
                self.thread_id(case_id),
                {
                    "case_id": case_id,
                    "input_id": input_id,
                    "input_hash": fingerprint,
                    "package": payload,
                    "artifact_sha256": fingerprint,
                },
            )
            self._sync(case_id)
            return self.get(case_id)

    def replace(self, case_id, revision, package):
        validated = ArchitecturePackage.model_validate(package)
        payload = validated.model_dump(mode="json")
        with (
            self.lock,
            self.store.lock(f"architecture:{case_id}") if self.store else nullcontext(),
        ):
            current = self.get(case_id)
            state = current["state"]
            if (
                state.get("status") != "changes_requested"
                or state["revision"] != revision
            ):
                raise ValueError("La revisión no está esperando correcciones.")
            self.catalog.validate(validated.baselines)
            new_revision = revision + 1
            digest = self.digest(payload)
            self.graph.update(
                self.thread_id(case_id),
                {
                    "package": payload,
                    "documents": validated.artifacts(),
                    "revision": new_revision,
                    "status": "awaiting_review",
                    "decision": "",
                    "artifact_sha256": digest,
                },
                after_step="validate_architecture",
            )
            self.graph.continue_run(self.thread_id(case_id))
            self._sync(case_id)
            return self.get(case_id)

    def review(self, case_id, revision, artifact_sha256, decision, feedback=""):
        if decision not in {"approve", "revise"}:
            raise ValueError("La decisión debe ser approve o revise.")
        if decision == "revise" and not feedback.strip():
            raise ValueError("Indicar los ajustes solicitados.")
        with (
            self.lock,
            self.store.lock(f"architecture:{case_id}") if self.store else nullcontext(),
        ):
            current = self.get(case_id)
            state = current["state"]
            if (
                state.get("status") != "awaiting_review"
                or state["revision"] != revision
                or state["artifact_sha256"] != artifact_sha256
            ):
                raise ValueError("Aprobar únicamente la revisión pendiente exacta.")
            self.graph.resume(
                self.thread_id(case_id),
                {"decision": decision, "feedback": feedback},
            )
            self._sync(case_id)
            return self.get(case_id)

    def _sync(self, case_id):
        if not self.store:
            return
        state = self.get(case_id)["state"]
        revision = state["revision"]
        self.store.phase(case_id, "stage-3", self.architect_id)
        self.store.put(
            f"architecture-artifact:{case_id}:{revision}",
            "architecture_artifact",
            {
                "case_id": case_id,
                "revision": revision,
                "artifact_sha256": state["artifact_sha256"],
                "package": state["package"],
                "documents": state["documents"],
            },
        )
        if state["status"] == "awaiting_review":
            self.store.event(
                f"architecture-review:{case_id}:{revision}",
                case_id,
                "approval.requested",
                {"actor": self.architect_id, "revision": revision},
            )
        if state["status"] == "ready_for_finops":
            self.store.complete_phase(case_id, "stage-3")
            self.store.create_handoff(
                f"{case_id}:stage-3:stage-4:v{revision}",
                case_id,
                self.architect_id,
                "finops-agent",
                "stage-3",
                "stage-4",
                revision=revision,
                artifact_sha256=state["artifact_sha256"],
            )
            if self.process:
                evidence = [f"architecture-artifact:{case_id}:{revision}"]
                current = self.process.get(case_id)["state"]
                if (
                    current["stage"] == 3
                    and current["status"] == "awaiting_deliverable"
                ):
                    self.process.internal(
                        case_id,
                        f"architecture.ready:{revision}:{state['artifact_sha256']}",
                        "deliverable.ready",
                        revision=revision,
                        artifact_sha256=state["artifact_sha256"],
                        evidence=evidence,
                    )
                current = self.process.get(case_id)["state"]
                if current["stage"] == 3 and current["status"] == "awaiting_review":
                    self.process.internal(
                        case_id,
                        f"architecture.approved:{revision}:{state['artifact_sha256']}",
                        "stage.approved",
                        revision=revision,
                        artifact_sha256=state["artifact_sha256"],
                        evidence=evidence,
                    )
