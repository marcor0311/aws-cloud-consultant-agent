"""Review and close a demo delivery with explicit, version-bound decisions."""

import os
from datetime import UTC, datetime
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
from app.delivery.workflow import public_result
from app.integrations.delivery_pdf import render_pdf
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
    def __init__(self, repository: PostgresRepository):
        self.repository = repository

    def get(self, delivery_id):
        row = self.repository.get(delivery_id)
        if not row:
            raise LookupError("Entrega no encontrada")
        result = public_result(row)
        result["report_decisions"] = self.repository.report_decisions(delivery_id)
        return result

    def decide(self, delivery_id, decision: ReportDecision, operator: str):
        data = decision.model_dump(mode="json")
        with self.repository.locked(delivery_id) as store:
            row = store.get()
            if not row or not row["report"]:
                raise LookupError("Informe no encontrado")
            prior = store.decision(decision.decision_id)
            if prior:
                if prior != {"decision": data, "operator": operator}:
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
            if report.status != required:
                raise DeliveryConflict(
                    f"La decisión requiere que el informe esté en estado {required}"
                )

            started = datetime.now(UTC)
            review_timing = PhaseTiming.model_validate(row["report_timing"])
            with store.conn.transaction():
                if decision.action in ("revise", "approve"):
                    request = DemoRequest.model_validate(
                        {
                            key: value
                            for key, value in row["request"].items()
                            if key in DemoRequest.model_fields
                        }
                    )
                    handoff = EngineeringHandoff.model_validate(row["handoff"])
                    report.metrics = calculate_metrics(
                        [*handoff.timings, review_timing]
                    )
                    if decision.action == "revise":
                        report.version += 1
                        report.report_id = uuid5(
                            delivery_id, f"report-v{report.version}"
                        )
                        report.revision_text = decision.detail
                        report.artifact = store.put_artifact(
                            f"informe-ejecutivo-v{report.version}.pdf",
                            "application/pdf",
                            render_pdf(
                                request,
                                handoff,
                                report.metrics,
                                version=report.version,
                                revision_text=report.revision_text,
                            ),
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
                            render_pdf(
                                request,
                                handoff,
                                report.metrics,
                                version=report.version,
                                revision_text=report.revision_text,
                                approval=approval,
                            ),
                        )
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
