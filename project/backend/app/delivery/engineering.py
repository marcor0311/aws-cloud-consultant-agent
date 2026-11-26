"""Record engineering input and existing evidence; never execute infrastructure."""

import base64
import re
from hashlib import sha256
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context

from app.delivery.engineering_models import EngineeringIntake, digest
from app.delivery.metrics import case_metrics
from app.persistence.delivery import DeliveryConflict


class IntakeState(TypedDict):
    recorded: bool


class EngineeringService:
    def __init__(self, repository, files, operator):
        if not operator or not operator.strip():
            raise ValueError("Configurar ENGINEERING_OPERATOR con el responsable local")
        self.repository, self.files, self.operator = repository, files, operator

    def _project(self, case_id):
        project = next(
            (
                p
                for p in self.repository.store.project_list(self.operator)
                if p["case_id"] == case_id
            ),
            None,
        )
        if not project:
            raise ValueError("Expediente inexistente o de otro responsable")
        return project

    def _upstream(self, request):
        store = self.repository.store
        if request.finops_architecture_sha256 != request.approval_digest(3):
            raise DeliveryConflict(
                "FinOps no referencia el manifiesto aprobado exacto de arquitectura"
            )
        state = store.get(f"process:{request.case_id}") or {}
        if state.get("stage") != 5 or state.get("status") != "awaiting_deliverable":
            raise DeliveryConflict(
                "El proceso no está esperando la entrega de ingeniería"
            )
        events = [
            e["payload"]
            for e in store.case_events(request.case_id)
            if e["kind"] == "process.transition"
        ]
        approvals = []
        for stage, package in ((3, request.architecture), (4, request.finops)):
            approval = next(
                (e for e in events if e.get("event_id") == package.approval.event_id),
                None,
            )
            if (
                not approval
                or (
                    approval.get("kind"),
                    approval.get("from_stage"),
                    approval.get("to_stage"),
                    approval.get("revision"),
                    approval.get("artifact_sha256"),
                    approval.get("actor"),
                )
                != (
                    "stage.approved",
                    stage,
                    stage + 1,
                    package.revision,
                    request.approval_digest(stage),
                    package.approval.actor,
                )
                or package.approval.reference not in approval.get("evidence", [])
            ):
                raise DeliveryConflict(
                    "Falta la decisión registrada sobre la versión y manifiesto exactos de Arquitectura o FinOps"
                )
            approvals.append(approval)
        if (
            approvals[0]["to_iteration"] != approvals[1]["from_iteration"]
            or approvals[1]["to_iteration"]
            != max(
                e["to_iteration"]
                for e in events
                if e.get("kind") == "stage.approved" and e.get("from_stage") == 4
            )
            or approvals[1]["to_iteration"] > state["iteration"]
        ):
            raise DeliveryConflict(
                "Las aprobaciones pertenecen a un ciclo anterior del proceso"
            )
        handoff = store.handoff(request.incoming_handoff_id)
        if (
            not handoff
            or (
                handoff["case_id"],
                handoff["from_phase"],
                handoff["to_phase"],
                handoff["to_actor"],
                handoff["from_actor"],
                handoff["revision"],
                handoff["artifact_sha256"],
            )
            != (
                request.case_id,
                "stage-4",
                "stage-5",
                self.operator,
                request.finops.approval.actor,
                request.finops.revision,
                request.approval_digest(4),
            )
            or handoff["accepted_by"] not in (None, self.operator)
        ):
            raise DeliveryConflict(
                "La entrega de FinOps no corresponde a este responsable o revisión"
            )
        return handoff

    def register(self, request):
        project = self._project(request.case_id)
        key = str(request.intake_id)
        input_sha256 = digest(request.model_dump(mode="json"))
        with (
            self.repository.store.lock(f"engineering:{key}"),
            self.repository.store.lock(f"process:{request.case_id}"),
        ):
            previous = self.repository.get(key)
            if previous:
                if (
                    previous["input_sha256"] != input_sha256
                    or previous["operator"] != self.operator
                ):
                    raise DeliveryConflict("El intake_id ya corresponde a otra entrada")
                return self.get(request.intake_id)

            def validate(_state):
                self._upstream(request)
                return {}

            def record(_state):
                handoff = self._upstream(request)
                files = self.files.read(
                    [*request.architecture.files, *request.finops.files]
                )
                self.repository.register(
                    request, input_sha256, self.operator, files, project, handoff
                )
                return {"recorded": True}

            graph = StateGraph(IntakeState)
            graph.add_node("validate_inputs", validate)
            graph.add_node("record_inputs", record)
            graph.add_edge(START, "validate_inputs")
            graph.add_edge("validate_inputs", "record_inputs")
            graph.add_edge("record_inputs", END)
            with tracing_context(enabled=False):
                graph.compile().invoke({"recorded": False})
        return self.get(request.intake_id)

    def record_evidence(self, evidence):
        intake = self.repository.get(evidence.intake_id)
        if not intake:
            raise LookupError("Entrada de ingeniería no encontrada")
        self._project(intake["case_id"])
        with (
            self.repository.store.lock(f"engineering:{evidence.intake_id}"),
            self.repository.store.lock(f"process:{intake['case_id']}"),
        ):
            if intake["operator"] != self.operator:
                raise ValueError("La entrada pertenece a otro responsable")
            evidence_sha256 = digest(evidence.model_dump(mode="json"))
            previous = self.repository.evidence(evidence.run_id)
            if previous:
                if (
                    previous["evidence_sha256"] != evidence_sha256
                    or previous["operator"] != self.operator
                ):
                    raise DeliveryConflict("El run_id ya corresponde a otra evidencia")
                return self.get(evidence.intake_id)
            request = EngineeringIntake.model_validate(intake["input"])
            self._upstream(request)
            if (
                self.repository.store.get(f"process:{intake['case_id']}")["iteration"]
                != intake["process_iteration"]
            ):
                raise DeliveryConflict(
                    "La iteración de ingeniería cambió; registrar una entrada nueva"
                )
            if evidence.input_sha256 != intake["input_sha256"] or sorted(
                [m.model_dump_json() for m in evidence.modules]
            ) != sorted([m.model_dump_json() for m in request.modules]):
                raise DeliveryConflict(
                    "La evidencia corresponde a otra entrada o versión de módulos"
                )
            now = self.repository.store.clock()
            for check in evidence.checks:
                if (
                    check.started_at is not None
                    and not intake["received_at"]
                    <= check.started_at.timestamp()
                    <= check.ended_at.timestamp()
                    <= now
                ):
                    raise ValueError(
                        "El intervalo técnico precede la recepción o termina en el futuro"
                    )
            prefix = f"https://github.com/{request.repository}/blob/{evidence.implementation_commit}/"
            if any(
                f.role == "implementation" and not f.reference.startswith(prefix)
                for f in evidence.files
            ):
                raise DeliveryConflict(
                    "La implementación pertenece a otro repositorio o commit"
                )
            files = self.files.read(evidence.files)
            self.repository.record(
                intake, evidence, evidence_sha256, self.operator, files
            )
        return self.get(evidence.intake_id)

    def get(self, intake_id):
        intake = self.repository.get(intake_id)
        if not intake:
            raise LookupError("Entrada de ingeniería no encontrada")
        self._project(intake["case_id"])
        if intake["operator"] != self.operator:
            raise ValueError("La entrada pertenece a otro responsable")
        try:
            self._upstream(EngineeringIntake.model_validate(intake["input"]))
            current = (
                self.repository.store.get(f"process:{intake['case_id']}")["iteration"]
                == intake["process_iteration"]
            )
        except DeliveryConflict:
            current = False
        runs = self.repository.runs(intake_id)
        metrics = case_metrics(
            self.repository.store.metrics(intake["case_id"]),
            self.repository.store.clock(),
        )
        return {
            "intake": intake,
            "evidence": runs,
            "evidence_status": runs[-1]["reported_status"] if runs else "not_received",
            "upstream_current": current,
            "phase_metrics": next(
                p for p in metrics["phases"] if p["phase"] == "engineering"
            ),
            "review_status": "pending",
            "integration_status": "no_pr",
            "blockers": [
                "Aprobación e integración del PR técnico pendientes.",
                "Las referencias de aprobación de baselines requieren verificación externa.",
            ]
            + (
                ["Faltan evidencias técnicas."]
                if not runs
                else (
                    [
                        "La última corrida informada tiene fallos o comprobaciones no ejecutadas."
                    ]
                    if runs[-1]["reported_status"] != "passed"
                    else []
                )
            )
            + (
                []
                if current
                else ["La entrada ya no corresponde al ciclo vigente del proceso."]
            ),
        }

    def read_file(self, intake_id, file_sha256):
        self.get(intake_id)  # Apply the same project/operator guard as receipt queries.
        if not re.fullmatch(r"[a-f0-9]{64}", file_sha256):
            raise ValueError("SHA-256 inválido")
        file = self.repository.file(intake_id, file_sha256)
        if not file:
            raise LookupError("Archivo no encontrado en esta entrada")
        content = base64.b64decode(file["content_base64"])
        if sha256(content).hexdigest() != file_sha256:
            raise DeliveryConflict("El respaldo del archivo no coincide con su hash")
        return content
