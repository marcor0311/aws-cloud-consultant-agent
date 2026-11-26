"""Intake boundary for the Cloud FinOps Agent."""

import hashlib
import json
from datetime import datetime, timezone

from app.architecture.corrections import FinOpsCorrectionRequest
from app.architecture.metrics import FinOpsHandoffAcceptance
from app.architecture.models import ArchitectureFinOpsHandoff
from app.architecture.service import ArchitectureService
from app.finops.analysis import FinOpsEconomicAnalyzer
from app.finops.calculator import PricingCalculatorPreparer
from app.finops.evidence import PricingCalculatorEvidence
from app.finops.models import (
    FinOpsEvaluationDecision,
    FinOpsIntake,
    FinOpsIssueSnapshot,
)


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


class FinOpsService:
    """Persisted application boundary exposed by the dedicated FinOps MCP."""

    def __init__(self, store, actor_id="finops-agent"):
        self.store = store
        self.intakes = FinOpsIntakeService(store, actor_id=actor_id)
        self.preparer = PricingCalculatorPreparer()
        self.analyzer = FinOpsEconomicAnalyzer()
        self.actor_id = actor_id

    @staticmethod
    def _digest(payload):
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

    def receive_handoff(self, case_id, handoff):
        return self.intakes.receive(case_id, handoff)

    def register_issue(self, case_id, revision, snapshot_payload):
        intake = FinOpsIntake.model_validate(self.intakes.get(case_id, revision))
        snapshot = FinOpsIssueSnapshot.model_validate(snapshot_payload)
        draft = self.store.get(
            f"architecture-finops-issue-draft:{case_id}:{revision}"
        )
        receipt = self.store.get(f"architecture-finops-issue:{case_id}:{revision}")
        approval = self.store.get(
            f"architecture-github-approval:{case_id}:{revision}"
        )
        if not draft or not receipt or not approval:
            raise ValueError(
                "Faltan el borrador, recibo o aprobación GitHub de Arquitectura."
            )
        if (
            snapshot.issue_url != receipt["issue_url"]
            or snapshot.issue_number != receipt["issue_number"]
            or snapshot.body_sha256 != receipt["body_sha256"]
            or snapshot.body_sha256 != draft["body_sha256"]
            or snapshot.repository_url != draft["repository_url"]
            or snapshot.assignees != draft["assignees"]
            or not set(draft["labels"]) <= set(snapshot.labels)
            or snapshot.architecture_revision != revision
            or snapshot.architecture_sha256 != intake.handoff.artifact_sha256
            or snapshot.architecture_issue_url != intake.handoff.source_issue
            or snapshot.architecture_pull_request_url
            != approval["pull_request_url"]
            or snapshot.architecture_merge_commit_sha
            != approval["merge_commit_sha"]
        ):
            raise ValueError("El issue FinOps no coincide con la entrega aprobada.")
        required_links = {
            snapshot.architecture_issue_url,
            snapshot.architecture_pull_request_url,
        }
        if not all(link in snapshot.body for link in required_links):
            raise ValueError("El issue FinOps no conserva los enlaces de Arquitectura.")
        if snapshot.architecture_merge_commit_sha not in snapshot.body:
            raise ValueError("El issue FinOps no conserva el merge commit aprobado.")

        payload = snapshot.model_dump(mode="json")
        key = f"finops-issue:{case_id}:{revision}"
        previous = self.store.get(key)
        if previous and previous != payload:
            raise ValueError("La revisión ya tiene otro snapshot del issue FinOps.")
        if not previous:
            self.store.put(key, "finops_issue_snapshot", payload)
            self.store.event(
                f"finops-issue:{case_id}:{revision}",
                case_id,
                "finops.issue_validated",
                {
                    "revision": revision,
                    "issue_url": snapshot.issue_url,
                    "architecture_sha256": snapshot.architecture_sha256,
                },
            )
        return {"duplicate": bool(previous), "issue": payload}

    def generate_aws_estimate(self, case_id, revision, evidence_payload=None):
        issue = self.store.get(f"finops-issue:{case_id}:{revision}")
        if not issue:
            raise ValueError("Primero se debe validar el issue asignado a FinOps.")
        preparation = self.prepare_calculator(case_id, revision)
        if evidence_payload is None:
            return {
                "status": "awaiting_codex_execution",
                "operator": "codex-browser",
                "calculator_url": "https://calculator.aws/",
                "plan": preparation["plan"],
                "required_evidence": [
                    "estimate_url",
                    "monthly_cost_and_currency",
                    "verified_parameters",
                    "csv_or_pdf_export_with_sha256",
                ],
                "may_mark_verified": False,
            }
        registered = self.register_evidence(case_id, revision, evidence_payload)
        return {
            "status": registered["evidence"]["status"],
            "operator": "codex-browser",
            "evidence": registered["evidence"],
            "duplicate": registered["duplicate"],
        }

    def intake_status(self, case_id, revision):
        intake = self.intakes.get(case_id, revision)
        handoff_id = f"{case_id}:stage-3:stage-4:v{revision}"
        return {
            "intake": intake,
            "persisted_handoff": self.store.handoff(handoff_id),
            "evidence_count": len(self._evidences(case_id, revision)),
            "has_analysis": bool(self.store.get(self._analysis_pointer(case_id, revision))),
            "issue": self.store.get(f"finops-issue:{case_id}:{revision}"),
        }

    def prepare_calculator(self, case_id, revision):
        intake = self.intakes.get(case_id, revision)
        preparation = self.preparer.prepare(intake).model_dump(mode="json")
        key = f"finops-calculator-plan:{case_id}:{revision}"
        previous = self.store.get(key)
        if previous and previous != preparation:
            raise ValueError("La revisión ya tiene otro plan de calculadora.")
        if not previous:
            self.store.put(key, "finops_calculator_plan", preparation)
            self.store.event(
                f"finops-plan:{case_id}:{revision}",
                case_id,
                "finops.calculator_plan_prepared",
                {"revision": revision},
            )
        return {"duplicate": bool(previous), "plan": preparation}

    def register_evidence(self, case_id, revision, evidence_payload):
        intake = FinOpsIntake.model_validate(self.intakes.get(case_id, revision))
        evidence = PricingCalculatorEvidence.model_validate(evidence_payload)
        self._validate_identity(intake, evidence)
        preparation_record = self.prepare_calculator(case_id, revision)
        resource = next(
            (
                item
                for item in preparation_record["plan"]["resources"]
                if item["resource_id"] == evidence.resource_id
            ),
            None,
        )
        if not resource or resource["status"] != "ready":
            raise ValueError("La evidencia corresponde a un recurso no preparado.")
        expected = {
            item["dimension_id"]: item for item in resource["dimensions"]
        }
        received = {item.dimension_id: item for item in evidence.parameters}
        if set(expected) != set(received):
            raise ValueError("La evidencia no cubre las dimensiones preparadas.")
        for dimension_id, parameter in received.items():
            planned = expected[dimension_id]
            if (
                parameter.calculator_parameter != planned["calculator_parameter"]
                or parameter.model_dump(mode="json")["planned_quantity"]
                != planned["quantity"]
                or parameter.unit != planned["unit"]
                or parameter.attributes != planned["attributes"]
            ):
                raise ValueError("La evidencia no coincide con el plan de calculadora.")
        payload = evidence.model_dump(mode="json")
        key = self._evidence_key(case_id, revision, evidence.resource_id)
        previous = self.store.get(key)
        if previous and previous != payload:
            raise ValueError("El recurso ya tiene otra evidencia para esta revisión.")
        if not previous:
            self.store.put(key, "finops_pricing_evidence", payload)
            self.store.event(
                f"finops-evidence:{case_id}:{revision}:{evidence.resource_id}",
                case_id,
                "finops.pricing_evidence_registered",
                {
                    "revision": revision,
                    "resource_id": evidence.resource_id,
                    "execution_id": evidence.execution_id,
                },
            )
        return {"duplicate": bool(previous), "evidence": payload}

    def run_analysis(self, case_id, revision):
        intake = self.intakes.get(case_id, revision)
        evidences = self._evidences(case_id, revision)
        analysis = self.analyzer.analyze(intake, evidences).model_dump(mode="json")
        analysis_id = "analysis-" + self._digest(analysis)
        reference = f"finops://{case_id}/analyses/{analysis_id}"
        record = {
            "analysis_id": analysis_id,
            "reference": reference,
            "analysis": analysis,
        }
        key = f"finops-analysis:{case_id}:{revision}:{analysis_id}"
        previous = self.store.get(key)
        if previous and previous != record:
            raise ValueError("El análisis persistido es inmutable.")
        if not previous:
            self.store.put(key, "finops_economic_analysis", record)
            self.store.event(
                f"finops-analysis:{case_id}:{revision}:{analysis_id}",
                case_id,
                "finops.analysis_completed",
                {
                    "revision": revision,
                    "analysis_id": analysis_id,
                    "status": analysis["operational_status"],
                },
            )
        self.store.put(self._analysis_pointer(case_id, revision), "finops_current", record)
        return {"duplicate": bool(previous), **record}

    def result(self, case_id, revision):
        record = self.store.get(self._analysis_pointer(case_id, revision))
        if not record:
            raise ValueError("La revisión todavía no tiene análisis FinOps.")
        return record

    def decide(self, case_id, revision, decision_payload):
        decision = FinOpsEvaluationDecision.model_validate(decision_payload)
        analysis_record = self.result(case_id, revision)
        analysis = analysis_record["analysis"]
        if (
            decision.case_id != case_id
            or decision.project_id != analysis["project_id"]
            or decision.architecture_revision != revision
            or decision.architecture_sha256 != analysis["architecture_sha256"]
            or decision.evaluation_reference != analysis_record["reference"]
        ):
            raise ValueError("La decisión no corresponde al análisis vigente.")
        if decision.budget_result != analysis["budget_result"]:
            raise ValueError("La decisión altera el resultado presupuestario.")
        if decision.decision == "approved" and (
            analysis["operational_status"] != "ready_for_decision"
            or not analysis["coverage"]["complete"]
            or analysis["budget_result"] == "not_evaluable"
        ):
            raise ValueError("No se puede aprobar una evaluación económica incompleta.")
        payload = decision.model_dump(mode="json")
        key = f"finops-decision:{case_id}:{revision}:{decision.decision_id}"
        previous = self.store.get(key)
        if previous and previous != payload:
            raise ValueError("El identificador de decisión ya tiene otro contenido.")
        if not previous:
            self.store.put(key, "finops_evaluation_decision", payload)
            self.store.event(
                f"finops-decision:{case_id}:{revision}:{decision.decision_id}",
                case_id,
                "finops.evaluation_decided",
                payload,
            )
        return {"duplicate": bool(previous), "decision": payload}

    def correction_request(self, case_id, revision, request_payload):
        request = FinOpsCorrectionRequest.model_validate(request_payload)
        intake = FinOpsIntake.model_validate(self.intakes.get(case_id, revision))
        analysis_record = self.result(case_id, revision)
        if (
            request.architecture_id != case_id
            or request.project_id != intake.project_id
            or request.source_revision != revision
            or request.finops_evaluation_reference != analysis_record["reference"]
        ):
            raise ValueError("La corrección no corresponde al análisis vigente.")
        resources = {item.resource_id for item in intake.handoff.architecture.resources}
        dimensions = {
            (pricing.resource_id, dimension.dimension_id)
            for pricing in intake.handoff.economic_contract.pricing_inputs
            for dimension in pricing.dimensions
        }
        if not set(request.affected_resources) <= resources or not {
            (item.resource_id, item.dimension_id)
            for item in request.affected_dimensions
        } <= dimensions:
            raise ValueError("La corrección referencia recursos o dimensiones ajenos.")
        decisions = [
            item
            for item in self.store.list("finops_evaluation_decision")
            if item["case_id"] == case_id
            and item["architecture_revision"] == revision
            and item["evaluation_reference"] == analysis_record["reference"]
            and item["decision"] == "architecture_correction_required"
        ]
        if not decisions:
            raise ValueError("La corrección requiere una decisión FinOps previa.")
        payload = request.model_dump(mode="json")
        key = f"finops-correction:{case_id}:{revision}:{request.request_id}"
        previous = self.store.get(key)
        if previous and previous != payload:
            raise ValueError("El identificador de corrección ya tiene otro contenido.")
        if not previous:
            self.store.put(key, "finops_correction_request", payload)
            self.store.event(
                f"finops-correction:{case_id}:{revision}:{request.request_id}",
                case_id,
                "finops.architecture_correction_requested",
                payload,
            )
        return {
            "duplicate": bool(previous),
            "request": payload,
            "handoff_to": "codex",
            "target_mcp": "aws_architecture",
            "target_tool": "solicitar_correccion_finops",
        }

    def history(self, case_id, revision):
        return {
            "case_id": case_id,
            "revision": revision,
            "intake": self.intakes.get(case_id, revision),
            "issue": self.store.get(f"finops-issue:{case_id}:{revision}"),
            "plan": self.store.get(f"finops-calculator-plan:{case_id}:{revision}"),
            "evidences": self._evidences(case_id, revision),
            "current_analysis": self.store.get(
                self._analysis_pointer(case_id, revision)
            ),
            "decisions": [
                item
                for item in self.store.list("finops_evaluation_decision")
                if item["case_id"] == case_id
                and item["architecture_revision"] == revision
            ],
            "corrections": [
                item
                for item in self.store.list("finops_correction_request")
                if item["architecture_id"] == case_id
                and item["source_revision"] == revision
            ],
        }

    @staticmethod
    def _validate_identity(intake, evidence):
        if (
            evidence.case_id != intake.case_id
            or evidence.project_id != intake.project_id
            or evidence.architecture_revision != intake.handoff.revision
            or evidence.architecture_sha256 != intake.handoff.artifact_sha256
        ):
            raise ValueError("La evidencia corresponde a otra arquitectura o revisión.")

    @staticmethod
    def _evidence_key(case_id, revision, resource_id):
        return f"finops-evidence:{case_id}:{revision}:{resource_id}"

    @staticmethod
    def _analysis_pointer(case_id, revision):
        return f"finops-current-analysis:{case_id}:{revision}"

    def _evidences(self, case_id, revision):
        prefix = f"finops-evidence:{case_id}:{revision}:"
        resources = self.intakes.get(case_id, revision)["handoff"]["architecture"][
            "resources"
        ]
        return [
            payload
            for resource in resources
            if (payload := self.store.get(prefix + resource["resource_id"])) is not None
        ]
