"""Independent, versioned executive report over a captured case."""

import json
from datetime import UTC, datetime
from hashlib import sha256
from typing import TypedDict
from uuid import uuid5

from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context

from app.delivery.metrics import calculate_metrics
from app.delivery.models import PhaseTiming, ReportDraft
from app.delivery.workflow import timing
from app.integrations.delivery_pdf import render_case_pdf
from app.persistence.delivery import DeliveryConflict


class ReportState(TypedDict):
    report_ready: bool


class ReportAccessDenied(ValueError):
    pass


def case_result(row):
    snapshot = row["request"]["snapshot"]
    return {
        "delivery_id": str(row["delivery_id"]),
        "case_id": snapshot["case_id"],
        "status": row["status"],
        "handoff": snapshot["technical"],
        "engineering": snapshot.get("engineering"),
        "report": row["report"],
        "error": row["error"],
        "metrics": snapshot["metrics"],
        "closure_blockers": snapshot["closure_blockers"],
        "captured_at": snapshot["captured_at"],
        "report_activity_metrics": calculate_metrics(
            [PhaseTiming.model_validate(row["report_timing"])]
            if row["report_timing"]
            else []
        ),
    }


def require_report_owner(row, operator):
    if (
        row["request"].get("kind") == "case_report"
        and row["request"]["operator"] != operator
    ):
        raise ReportAccessDenied("El informe pertenece a otro responsable")


class CaseReportService:
    def __init__(self, repository, sources, operator, process=None):
        if not operator or not operator.strip():
            raise ValueError("Configurar el responsable del informe")
        self.repository, self.sources, self.operator = repository, sources, operator
        self.process = process

    def generate(self, request):
        identity = {
            "kind": "case_report",
            # Preserve request hashes of reports created before intake selection.
            "input": request.model_dump(
                mode="json",
                exclude={"intake_id"} if request.intake_id is None else set(),
            ),
            "operator": self.operator,
        }
        digest = sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        with self.repository.locked(request.report_id) as store:
            row = store.get()
            if row:
                if row["request_hash"] != digest:
                    raise DeliveryConflict(
                        "El identificador corresponde a otro expediente o entrada"
                    )
                if row["report"]:
                    return case_result(row)

            def capture(_state):
                if not store.get():
                    snapshot = self.sources.capture(request, self.operator)
                    store.create({**identity, "snapshot": snapshot}, digest)
                return {}

            def render(_state):
                snapshot = store.get()["request"]["snapshot"]
                started = datetime.now(UTC)
                sections = {
                    "results": snapshot["engineering"]["summary"]
                    if snapshot.get("engineering")
                    else snapshot["technical"]["summary"]
                    if snapshot["technical"]
                    else "Entrega técnica pendiente. Este informe consolida los registros disponibles del expediente.",
                    "risks": " ".join(snapshot["engineering"]["blockers"])
                    if snapshot.get("engineering")
                    and snapshot["engineering"]["blockers"]
                    else "Revisar los límites de compatibilidad y las mediciones sin clasificar indicadas en las fuentes."
                    if not snapshot["closure_blockers"]
                    else "El informe es parcial. Los faltantes y las fuentes simuladas requieren conciliación antes del cierre.",
                    "next_steps": "Revisar y aprobar el informe definitivo; registrar su presentación a dirección para cerrar el expediente."
                    if not snapshot["closure_blockers"]
                    else "Revisar los resultados importados, resolver fallos o pendientes, verificar baselines y obtener revisión e integración del PR de ingeniería."
                    if snapshot.get("engineering")
                    else "Completar arquitectura, FinOps y entrega técnica aprobada; revisar las mediciones y presentar el informe definitivo a dirección.",
                }
                with store.conn.transaction():
                    source = store.put_artifact(
                        "fuentes-informe.json",
                        "application/json",
                        json.dumps(
                            snapshot, ensure_ascii=False, sort_keys=True, indent=2
                        ).encode(),
                    )
                    artifact = store.put_artifact(
                        "informe-ejecutivo-v1.pdf",
                        "application/pdf",
                        render_case_pdf(
                            snapshot,
                            sections,
                            version=1,
                            source=source.model_dump(mode="json"),
                        ),
                    )
                    report = ReportDraft(
                        report_id=uuid5(request.report_id, "report-v1"),
                        handoff_id=snapshot["technical"]["handoff_id"]
                        if snapshot["technical"]
                        else None,
                        intake_id=request.intake_id,
                        artifact=artifact,
                        sources=source,
                        sections=sections,
                        metrics=snapshot["metrics"],
                        pending_items=snapshot["closure_blockers"],
                    )
                    store.save_report(
                        report.model_dump(mode="json"),
                        timing("report", started, datetime.now(UTC)).model_dump(
                            mode="json"
                        ),
                    )
                return {"report_ready": True}

            graph = StateGraph(ReportState)
            graph.add_node("capture_case", capture)
            graph.add_node("executive_report_agent", render)
            graph.add_edge(START, "capture_case")
            graph.add_edge("capture_case", "executive_report_agent")
            graph.add_edge("executive_report_agent", END)
            try:
                with tracing_context(enabled=False):
                    graph.compile().invoke({"report_ready": False})
            except Exception:
                if store.get():
                    store.failed()
                raise
            return case_result(store.get())

    def read_engineering_file(self, report_id, file_sha256):
        row = self.repository.get(report_id)
        if not row or row["request"].get("kind") != "case_report":
            raise LookupError("Informe por expediente no encontrado")
        require_report_owner(row, self.operator)
        engineering = row["request"]["snapshot"].get("engineering")
        if not engineering or not any(
            f["sha256"] == file_sha256 for f in engineering["files"]
        ):
            raise LookupError("Archivo no incluido en las fuentes de este informe")
        return self.sources.engineering.read_file(
            engineering["intake"]["intake_id"], file_sha256
        )

    def record_presentation(self, row, decision, operator):
        """Close the real process first, with deterministic events for crash recovery."""
        from app.delivery.models import CaseReportRequest

        require_report_owner(row, operator)
        if operator != self.operator or self.process is None:
            raise DeliveryConflict(
                "El cierre del proceso no está configurado para este responsable"
            )
        snapshot = row["request"]["snapshot"]
        if snapshot["closure_blockers"]:
            raise DeliveryConflict(
                "No se puede cerrar el expediente: "
                + "; ".join(snapshot["closure_blockers"])
            )
        if decision.presentation is None:
            raise DeliveryConflict(
                "Registrar fecha, audiencia y referencia de la presentación a dirección"
            )
        approvals = [
            d
            for d in self.repository.report_decisions(row["delivery_id"])
            if d["decision"]["action"] == "approve"
        ]
        if not approvals or not approvals[-1][
            "created_at"
        ] <= decision.presentation.presented_at <= datetime.now(UTC):
            raise DeliveryConflict(
                "La presentación debe ser posterior a la aprobación y no estar en el futuro"
            )
        request = CaseReportRequest.model_validate(row["request"]["input"])
        engineering = snapshot.get("engineering")
        if (
            not engineering
            or not engineering.get("release")
            or snapshot["project"]["is_fictitious"]
        ):
            raise DeliveryConflict(
                "El cierre requiere una entrega técnica definitiva de un expediente real"
            )
        report = row["report"]
        if not report.get("approved_document"):
            raise DeliveryConflict("Falta el PDF aprobado de esta revisión")
        for ref in (report["artifact"], report["approved_document"]):
            artifact = self.repository.artifact(row["delivery_id"], ref["artifact_id"])
            if (
                not artifact
                or sha256(bytes(artifact["content"])).hexdigest() != ref["sha256"]
            ):
                raise DeliveryConflict("El PDF no coincide con la revisión aprobada")
        case_id = snapshot["case_id"]
        token = f"report:{row['delivery_id']}:{decision.decision_id}"
        base = {
            "stage": 6,
            "iteration": snapshot["process"]["iteration"],
            "actor": operator,
            "origin": "operator",
            "revision": report["version"],
            "artifact_sha256": report["artifact"]["sha256"],
            "evidence": [
                f"delivery://pdf/{row['delivery_id']}/{report['artifact']['artifact_id']}",
                f"delivery://pdf/{row['delivery_id']}/{report['approved_document']['artifact_id']}",
                decision.presentation.reference,
            ],
            "presentation": decision.presentation.model_dump(mode="json"),
            "comment": decision.detail,
        }
        events = [
            {**base, "event_id": token + ":ready", "kind": "deliverable.ready"},
            {**base, "event_id": token + ":presented", "kind": "stage.approved"},
        ]

        def guard(state):
            replay = any(e["event_id"] == token + ":ready" for e in state["history"])
            if (
                state["stage"] != 6
                or state["iteration"] != base["iteration"]
                or (not replay and state["status"] != "awaiting_deliverable")
            ):
                raise DeliveryConflict(
                    "El proceso cambió o ya existe otra presentación; conciliar antes del cierre"
                )
            current = self.sources._capture(request, operator)
            if current["closure_blockers"] or (
                current["engineering"]["release"]["release_sha256"]
                != engineering["release"]["release_sha256"]
                or current["engineering"]["catalog"]["sha256"]
                != engineering["catalog"]["sha256"]
            ):
                raise DeliveryConflict(
                    "La entrega técnica cambió; generar y aprobar un informe nuevo"
                )

        # Same lock ordering as imports/capture; the process service owns its lock.
        with self.sources.store.lock(f"engineering:{request.intake_id}"):
            self.process.apply_sequence(case_id, events, guard)
            self.sources.store.complete_phase(case_id, "stage-6")
