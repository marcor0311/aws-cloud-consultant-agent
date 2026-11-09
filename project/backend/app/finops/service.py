"""Intake boundary for the Cloud FinOps Agent."""

from datetime import datetime, timezone

from app.architecture.metrics import FinOpsHandoffAcceptance
from app.architecture.models import ArchitectureFinOpsHandoff
from app.architecture.service import ArchitectureService
from app.finops.models import FinOpsIntake


class FinOpsIntakeService:
    """Validate and persist receipt without pricing or evaluating the budget."""

    def __init__(self, store, actor_id="finops-agent"):
        self.store = store
        self.actor_id = actor_id

    @staticmethod
    def _key(case_id, revision):
        return f"finops-intake:{case_id}:{revision}"

    def receive(self, case_id, handoff_payload):
        handoff = ArchitectureFinOpsHandoff.model_validate(handoff_payload)
        if handoff.handoff_status != "ready":
            raise ValueError("FinOps no puede recibir un handoff bloqueado.")
        calculated_sha = ArchitectureService.digest(
            handoff.architecture.model_dump(mode="json")
        )
        if calculated_sha != handoff.artifact_sha256:
            raise ValueError("El SHA-256 no corresponde a la arquitectura entregada.")

        handoff_id = f"{case_id}:stage-3:stage-4:v{handoff.revision}"
        persisted = self.store.handoff(handoff_id)
        if not persisted:
            raise ValueError("La entrega de Arquitectura no existe en persistencia.")
        if (
            persisted["case_id"] != case_id
            or persisted["to_actor"] != self.actor_id
            or persisted["revision"] != handoff.revision
            or persisted["artifact_sha256"] != handoff.artifact_sha256
        ):
            raise ValueError("La entrega persistida no coincide con el handoff.")

        key = self._key(case_id, handoff.revision)
        previous = self.store.get(key)
        if previous:
            previous_intake = FinOpsIntake.model_validate(previous)
            if previous_intake.handoff != handoff:
                raise ValueError("La revisión ya tiene otra recepción FinOps.")
            return {"duplicate": True, "intake": previous_intake.model_dump(mode="json")}

        accepted_at = datetime.fromtimestamp(self.store.clock(), timezone.utc)
        acceptance = FinOpsHandoffAcceptance(
            case_id=case_id,
            revision=handoff.revision,
            artifact_sha256=handoff.artifact_sha256,
            accepted_by=self.actor_id,
            accepted_at=accepted_at,
            finops_reference=(
                f"finops://{case_id}/intakes/{handoff.revision}/"
                f"{handoff.artifact_sha256}"
            ),
        )
        intake = FinOpsIntake(
            case_id=case_id,
            project_id=handoff.architecture.project_id,
            handoff=handoff,
            acceptance=acceptance,
        )
        payload = intake.model_dump(mode="json")
        self.store.accept_handoff(
            handoff_id, self.actor_id, acceptance.accepted_at.timestamp()
        )
        self.store.put(key, "finops_intake", payload)
        self.store.event(
            f"finops-intake:{case_id}:{handoff.revision}",
            case_id,
            "finops.handoff_received",
            {
                "revision": handoff.revision,
                "artifact_sha256": handoff.artifact_sha256,
            },
        )
        return {"duplicate": False, "intake": payload}

    def get(self, case_id, revision):
        payload = self.store.get(self._key(case_id, revision))
        if not payload:
            raise ValueError("La recepción FinOps no existe.")
        return FinOpsIntake.model_validate(payload).model_dump(mode="json")
