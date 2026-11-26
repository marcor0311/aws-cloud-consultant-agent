"""Review and close a demo delivery with explicit, version-bound decisions."""

import os
from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid5

from app.delivery.metrics import calculate_metrics
from app.delivery.models import (
    Activity,
    DemoRequest,
    EngineeringHandoff,
    PhaseTiming,
    ReportDecision,
    ReportDraft,
)
from app.delivery.report import require_report_owner
from app.delivery.workflow import public_result
from app.integrations.delivery_pdf import render_case_pdf, render_pdf
from app.persistence.delivery import DeliveryConflict, PostgresRepository

TRANSITIONS = {
    "request_changes": ("draft", "changes_requested"),
    "revise": ("changes_requested", "draft"),
    "approve": ("draft", "approved"),
    "record_presentation": ("approved", "closed"),
}


def configured_manager() -> str:
    operator = os.getenv("DELIVERY_ENGAGEMENT_MANAGER", "").strip()
    if not operator:
        raise ValueError(
            "Configurar DELIVERY_ENGAGEMENT_MANAGER para el operador local"
        )
    return operator


class ReportReview:
    def __init__(self, repository: PostgresRepository, operator=None):
        self.repository, self.operator = repository, operator

    def get(self, delivery_id):
        row = self.repository.get(delivery_id)
        if not row:
            raise LookupError("Entrega no encontrada")
        require_report_owner(row, self.operator)
        result = public_result(row)
        result["report_decisions"] = self.repository.report_decisions(delivery_id)
        return result

    def decide(self, delivery_id, decision: ReportDecision, operator: str):
        data = decision.model_dump(mode="json", exclude_defaults=True)
        with self.repository.locked(delivery_id) as store:
            row = store.get()
            if not row or not row["report"]:
                raise LookupError("Informe no encontrado")
            require_report_owner(row, operator)
            prior = store.decision(decision.decision_id)
            if prior:
                if (
                    ReportDecision.model_validate(prior["decision"]).model_dump(
                        mode="json", exclude_defaults=True
                    )
                    != data
                    or prior["operator"] != operator
                ):
                    raise DeliveryConflict(
                        "El identificador corresponde a otra decisión"
                    )
                return public_result(row)

            report = ReportDraft.model_validate(row["report"])
            if (decision.version, decision.sha256) != (
                report.version,
                report.artifact.sha256,
            ):
                raise DeliveryConflict(
                    "La versión o SHA-256 del informe no es el vigente"
                )
            required, next_status = TRANSITIONS[decision.action]
            if report.status != required and not (
                decision.action == "request_changes" and report.status == "approved"
            ):
                raise DeliveryConflict(
                    f"La decisión requiere que el informe esté en estado {required}"
                )

            is_case = row["request"].get("kind") == "case_report"
            if not is_case and decision.sections:
                raise DeliveryConflict(
                    "La corrección por secciones requiere un informe por expediente"
                )
            if is_case and decision.action == "record_presentation":
                raise DeliveryConflict(
                    "No se puede cerrar el expediente: "
                    + "; ".join(row["request"]["snapshot"]["closure_blockers"])
                )
            if is_case and decision.action == "revise" and not decision.sections:
                raise DeliveryConflict("Indicar las secciones corregidas en sections")
            if is_case:
                source = self.repository.artifact(
                    delivery_id, report.sources.artifact_id
                )
                if (
                    not source
                    or sha256(bytes(source["content"])).hexdigest()
                    != report.sources.sha256
                ):
                    raise DeliveryConflict(
                        "El respaldo de fuentes no coincide con la revisión"
                    )
            started = datetime.now(UTC)
            review_timing = PhaseTiming.model_validate(row["report_timing"])
            with store.conn.transaction():
                if decision.action in ("revise", "approve"):
                    request = (
                        None
                        if is_case
                        else DemoRequest.model_validate(
                            {
                                key: value
                                for key, value in row["request"].items()
                                if key in DemoRequest.model_fields
                            }
                        )
                    )
                    handoff = (
                        None
                        if is_case
                        else EngineeringHandoff.model_validate(row["handoff"])
                    )
                    if not is_case:
                        report.metrics = calculate_metrics(
                            [*handoff.timings, review_timing]
                        )

                    def render(approval=None):
                        if is_case:
                            return render_case_pdf(
                                row["request"]["snapshot"],
                                report.sections,
                                version=report.version,
                                source=report.sources.model_dump(mode="json"),
                                approval=approval,
                            )
                        return render_pdf(
                            request,
                            handoff,
                            report.metrics,
                            version=report.version,
                            revision_text=report.revision_text,
                            approval=approval,
                        )

                    if decision.action == "revise":
                        report.version += 1
                        report.report_id = uuid5(
                            delivery_id, f"report-v{report.version}"
                        )
                        report.revision_text = decision.detail
                        report.sections.update(decision.sections)
                        report.approved_document = None
                        report.artifact = store.put_artifact(
                            f"informe-ejecutivo-v{report.version}.pdf",
                            "application/pdf",
                            render(),
                        )
                    else:
                        approval = {
                            "operator": operator,
                            "sha256": report.artifact.sha256,
                            "detail": decision.detail,
                            "at": datetime.now(UTC).isoformat(),
                        }
                        report.approved_document = store.put_artifact(
                            f"informe-ejecutivo-v{report.version}-aprobado.pdf",
                            "application/pdf",
                            render(approval),
                        )
                if decision.action == "request_changes":
                    report.approved_document = None
                report.status = next_status
                ended = datetime.now(UTC)
                if decision.action in ("revise", "approve"):
                    review_timing.activities.append(
                        Activity(
                            actor_id="agent-report",
                            actor_type="agent",
                            kind="rework" if decision.action == "revise" else "work",
                            started_at=started,
                            ended_at=ended,
                        )
                    )
                review_timing.handed_off_at = ended
                store.save_decision(
                    decision.decision_id,
                    data,
                    operator,
                    report.model_dump(mode="json"),
                    review_timing.model_dump(mode="json"),
                )
            return public_result(store.get())
