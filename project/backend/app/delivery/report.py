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
    def __init__(self, repository, sources, operator):
        if not operator or not operator.strip():
            raise ValueError("Configurar el responsable del informe")
        self.repository, self.sources, self.operator = repository, sources, operator

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
                    else "El informe es parcial. Los faltantes y las fuentes simuladas requieren conciliación antes del cierre.",
                    "next_steps": "Revisar los resultados importados, resolver fallos o pendientes, verificar baselines y obtener revisión e integración del PR de ingeniería."
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
