"""Intake boundary for the Cloud FinOps Agent."""

import base64
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from app.architecture.corrections import FinOpsCorrectionRequest
from app.architecture.metrics import FinOpsHandoffAcceptance
from app.architecture.models import ArchitectureFinOpsHandoff
from app.architecture.service import ArchitectureService
from app.finops.analysis import FinOpsEconomicAnalyzer
from app.finops.calculator import PricingCalculatorPreparer
from app.finops.engineering_delivery import (
    EngineeringHandoffAcceptance,
    EngineeringIssuePlan,
    EngineeringIssueReceipt,
    FinOpsEngineeringHandoff,
)
from app.finops.evidence import PricingCalculatorEvidence
from app.finops.github_delivery import (
    FinOpsCorrectionGitHubPlan,
    FinOpsCorrectionGitHubReceipt,
    FinOpsGitHubFile,
    FinOpsGitHubMergeReceipt,
    FinOpsGitHubPublicationPlan,
    FinOpsGitHubPullRequestReceipt,
)
from app.finops.models import (
    FinOpsCommentRequest,
    FinOpsEvaluationDecision,
    FinOpsIntake,
    FinOpsIssueSnapshot,
)
from app.finops.workbook import ForecastWorkbookGenerator


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
        self.store.phase(case_id, "stage-4", self.actor_id)
        return {"duplicate": False, "intake": payload}

    def get(self, case_id, revision):
        payload = self.store.get(self._key(case_id, revision))
        if not payload:
            raise ValueError("La recepción FinOps no existe.")
        return FinOpsIntake.model_validate(payload).model_dump(mode="json")


class FinOpsService:
    """Persisted application boundary exposed by the dedicated FinOps MCP."""

    def __init__(self, store, actor_id="finops-agent", output_dir=None):
        self.store = store
        self.intakes = FinOpsIntakeService(store, actor_id=actor_id)
        self.preparer = PricingCalculatorPreparer()
        self.analyzer = FinOpsEconomicAnalyzer()
        self.actor_id = actor_id
        self.output_dir = Path(
            output_dir
            or Path(__file__).resolve().parents[2] / "data" / "finops"
        )
        self.workbooks = ForecastWorkbookGenerator()

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

    def generate_workbook(self, case_id, revision):
        intake = FinOpsIntake.model_validate(self.intakes.get(case_id, revision))
        analysis_record = self.result(case_id, revision)
        analysis = self.analyzer.analyze(
            intake,
            self._evidences(case_id, revision),
        )
        if analysis.model_dump(mode="json") != analysis_record["analysis"]:
            raise ValueError("El análisis vigente no coincide con sus evidencias.")
        evidences = [
            PricingCalculatorEvidence.model_validate(item)
            for item in self._evidences(case_id, revision)
        ]
        source_digest = self.workbooks.source_digest(intake, analysis, evidences)
        key = f"finops-workbook:{case_id}:{revision}:{source_digest}"
        previous = self.store.get(key)
        if previous:
            target = self.output_dir / previous["relative_path"]
            if not target.exists():
                raise ValueError("El forecast.xlsx persistido ya no existe en disco.")
            actual_sha = hashlib.sha256(target.read_bytes()).hexdigest()
            if actual_sha != previous["file_sha256"]:
                raise ValueError("forecast.xlsx cambió después de su generación.")
            return {"duplicate": True, "workbook": previous}
        artifact = self.workbooks.generate(
            self.output_dir,
            intake,
            analysis,
            evidences,
        ).model_dump(mode="json")
        self.store.put(key, "finops_forecast_workbook", artifact)
        self.store.put(
            f"finops-workbook-current:{case_id}:{revision}",
            "finops_current",
            artifact,
        )
        self.store.event(
            f"finops-workbook:{case_id}:{revision}:{artifact['source_digest']}",
            case_id,
            "finops.workbook_generated",
            artifact,
        )
        return {"duplicate": False, "workbook": artifact}

    def prepare_comment(self, case_id, revision, request_payload):
        request = FinOpsCommentRequest.model_validate(request_payload)
        issue = self.store.get(f"finops-issue:{case_id}:{revision}")
        analysis_record = self.result(case_id, revision)
        if not issue:
            raise ValueError("Primero se debe validar el issue FinOps.")
        analysis = analysis_record["analysis"]
        mention = (
            f"@{request.architect_github_username} "
            if request.architect_github_username
            else ""
        )
        body = (
            f"{mention}{request.message}\n\n"
            f"Evaluación: {analysis_record['reference']}\n"
            f"Arquitectura: revisión {revision}, `{analysis['architecture_sha256']}`\n"
            f"Cobertura de recursos: "
            f"{analysis['coverage']['resource_coverage_percent']}%\n"
            f"Resultado presupuestario: {analysis['budget_result']}\n"
            f"Issue de Arquitectura: {issue['architecture_issue_url']}"
        )
        payload = {
            **request.model_dump(mode="json"),
            "issue_url": issue["issue_url"],
            "analysis_reference": analysis_record["reference"],
            "architecture_sha256": analysis["architecture_sha256"],
            "body": body,
            "body_sha256": hashlib.sha256(body.encode()).hexdigest(),
            "publication_status": "draft",
        }
        key = f"finops-comment:{case_id}:{revision}:{request.comment_id}"
        previous = self.store.get(key)
        if previous and previous != payload:
            raise ValueError("El identificador de comentario ya tiene otro contenido.")
        if not previous:
            self.store.put(key, "finops_comment_draft", payload)
        return {"duplicate": bool(previous), "comment": payload}

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
                {**payload, "requires_rework": True},
            )
        return {
            "duplicate": bool(previous),
            "request": payload,
            "handoff_to": "codex",
            "target_mcp": "aws_architecture",
            "target_tool": "solicitar_correccion_finops",
        }

    def prepare_correction_github(self, case_id, revision, request_id, architect):
        intake = FinOpsIntake.model_validate(self.intakes.get(case_id, revision))
        issue = self.store.get(f"finops-issue:{case_id}:{revision}")
        request = self.store.get(f"finops-correction:{case_id}:{revision}:{request_id}")
        if not issue or not request:
            raise ValueError("Faltan el issue FinOps o la solicitud de corrección.")
        analysis = self.result(case_id, revision)
        affected = ", ".join(request["affected_resources"])
        closing = (
            f"Se requiere ajustar la Arquitectura. Solicitud: `{request_id}`.\n\n"
            f"Motivo: {request['reason']}\n\n"
            f"Evaluación: {analysis['reference']}"
        )
        body = (
            f"@{architect} FinOps solicita una nueva revisión de Arquitectura.\n\n"
            f"Issue FinOps cerrado: {issue['issue_url']}\n\n"
            f"Issue de Arquitectura anterior: {issue['architecture_issue_url']}\n\n"
            f"Revisión afectada: {revision}; SHA-256: "
            f"`{issue['architecture_sha256']}`\n\n"
            f"Recursos afectados: {affected}\n\n"
            f"Motivo: {request['reason']}\n\n"
            "Cambios solicitados:\n- "
            + "\n- ".join(request["requested_changes"])
            + f"\n\nEvaluación: {analysis['reference']}"
        )
        plan = FinOpsCorrectionGitHubPlan(
            case_id=case_id,
            project_id=intake.project_id,
            architecture_revision=revision,
            architecture_sha256=issue["architecture_sha256"],
            correction_request_id=request_id,
            repository_url=issue["repository_url"],
            finops_issue_url=issue["issue_url"],
            closing_comment=closing,
            closing_comment_sha256=hashlib.sha256(closing.encode()).hexdigest(),
            architect_github_username=architect,
            correction_issue_title=(
                f"[Arquitectura] Corrección FinOps v{revision:03d}"
            ),
            correction_issue_body=body,
            correction_issue_labels=["architecture", "architecture-correction"],
            correction_issue_assignees=[architect],
            correction_issue_body_sha256=hashlib.sha256(body.encode()).hexdigest(),
        ).model_dump(mode="json")
        record = {"plan_sha256": self._digest(plan), "plan": plan}
        key = f"finops-correction-github-plan:{case_id}:{revision}:{request_id}"
        previous = self.store.get(key)
        if previous and previous != record:
            raise ValueError("El plan GitHub de corrección es inmutable.")
        if not previous:
            self.store.put(key, "finops_correction_github_plan", record)
        return {"duplicate": bool(previous), **record}

    def register_correction_github(self, case_id, revision, request_id, receipt):
        validated = FinOpsCorrectionGitHubReceipt.model_validate(receipt)
        key = f"finops-correction-github-plan:{case_id}:{revision}:{request_id}"
        record = self.store.get(key)
        if not record:
            raise ValueError("Primero se debe preparar el plan GitHub de corrección.")
        plan = record["plan"]
        if (
            validated.plan_sha256 != record["plan_sha256"]
            or validated.finops_issue_url != plan["finops_issue_url"]
            or "requiere-ajustes" not in validated.finops_issue_labels
            or validated.finops_closing_comment_sha256
            != plan["closing_comment_sha256"]
            or validated.correction_issue_body_sha256
            != plan["correction_issue_body_sha256"]
            or validated.correction_issue_assignees
            != plan["correction_issue_assignees"]
            or not validated.correction_issue_url.startswith(
                plan["repository_url"] + "/issues/"
            )
        ):
            raise ValueError("El recibo GitHub no corresponde al plan de corrección.")
        payload = validated.model_dump(mode="json")
        receipt_key = f"finops-correction-github:{case_id}:{revision}:{request_id}"
        previous = self.store.get(receipt_key)
        if previous and previous != payload:
            raise ValueError("La corrección ya tiene otro recibo GitHub.")
        if not previous:
            self.store.put(receipt_key, "finops_correction_github_receipt", payload)
            for url, kind in (
                (validated.finops_issue_url, "finops_issue"),
                (validated.correction_issue_url, "architecture_correction_issue"),
            ):
                self.store.put(
                    "finops-github-url:" + hashlib.sha256(url.encode()).hexdigest(),
                    "finops_github_link",
                    {
                        "case_id": case_id,
                        "revision": revision,
                        "url": url,
                        "kind": kind,
                    },
                )
            self.store.event(
                receipt_key,
                case_id,
                "finops.correction_published",
                payload,
            )
        return {"duplicate": bool(previous), "receipt": payload}

    def prepare_github_publication(self, case_id, revision, decision_id):
        issue = self.store.get(f"finops-issue:{case_id}:{revision}")
        analysis_record = self.result(case_id, revision)
        workbook = self.store.get(f"finops-workbook-current:{case_id}:{revision}")
        decision = self.store.get(f"finops-decision:{case_id}:{revision}:{decision_id}")
        if not issue or not workbook or not decision:
            raise ValueError("Faltan issue, forecast.xlsx o decisión FinOps.")
        analysis = analysis_record["analysis"]
        if (
            decision["contract_version"] != "1.1"
            or decision["decision"] != "approved"
            or not decision.get("authorization")
            or analysis["operational_status"] != "ready_for_decision"
            or not analysis["coverage"]["complete"]
            or analysis["budget_result"] == "not_evaluable"
            or workbook["status"] != "generated"
        ):
            raise ValueError("La publicación exige evaluación completa y autorizada.")
        prefix = f"docs/04-finops/versions/v{revision:03d}"
        workbook_path = self.output_dir / workbook["relative_path"]
        if not workbook_path.is_file():
            raise ValueError("forecast.xlsx no existe en la ruta persistida.")
        workbook_raw = workbook_path.read_bytes()
        if hashlib.sha256(workbook_raw).hexdigest() != workbook["file_sha256"]:
            raise ValueError("forecast.xlsx no coincide con su registro persistido.")
        analysis_raw = (json.dumps(analysis_record, ensure_ascii=False, indent=2) + "\n").encode()
        evidence_raw = (
            json.dumps(self._evidences(case_id, revision), ensure_ascii=False, indent=2)
            + "\n"
        ).encode()
        raw_files = {
            "forecast.xlsx": workbook_raw,
            "analysis.json": analysis_raw,
            "pricing-evidence.json": evidence_raw,
        }
        manifest = {
            "contract_version": "1.0",
            "project_id": analysis["project_id"],
            "architecture_revision": revision,
            "architecture_sha256": analysis["architecture_sha256"],
            "decision_id": decision_id,
            "authorization_id": decision["authorization"]["authorization_id"],
            "files": [
                {"path": name, "sha256": hashlib.sha256(raw).hexdigest()}
                for name, raw in sorted(raw_files.items())
            ],
        }
        raw_files["manifest.json"] = (
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
        ).encode()
        files = [
            FinOpsGitHubFile(
                path=f"{prefix}/{name}",
                encoding="base64" if name.endswith(".xlsx") else "utf-8",
                content=(
                    base64.b64encode(raw).decode()
                    if name.endswith(".xlsx")
                    else raw.decode()
                ),
                sha256=hashlib.sha256(raw).hexdigest(),
            ).model_dump(mode="json")
            for name, raw in sorted(raw_files.items())
        ]
        plan = FinOpsGitHubPublicationPlan(
            case_id=case_id,
            project_id=analysis["project_id"],
            architecture_revision=revision,
            architecture_sha256=analysis["architecture_sha256"],
            decision_id=decision_id,
            authorization_id=decision["authorization"]["authorization_id"],
            repository_url=issue["repository_url"],
            source_issue_url=issue["issue_url"],
            base_commit=issue["architecture_merge_commit_sha"],
            branch=f"agent4/{analysis['project_id']}/finops-v{revision:03d}",
            commit_message=f"docs(finops): publish revision {revision}",
            pull_request_title=f"[FinOps] {analysis['project_id']} v{revision:03d}",
            pull_request_body=(
                f"Publica costos FinOps autorizados para la revisión {revision}.\n\n"
                f"Issue: {issue['issue_url']}\n\n"
                f"Arquitectura: `{analysis['architecture_sha256']}`\n\n"
                f"Autorización FinOps: `{decision['authorization']['authorization_id']}`\n\n"
                "No requiere revisión del arquitecto. El merge exige checks exitosos."
            ),
            files=files,
        ).model_dump(mode="json")
        record = {"plan_sha256": self._digest(plan), "plan": plan}
        key = f"finops-github-plan:{case_id}:{revision}"
        previous = self.store.get(key)
        if previous and previous != record:
            raise ValueError("El plan GitHub FinOps de la revisión es inmutable.")
        if not previous:
            self.store.put(key, "finops_github_plan", record)
        return {"duplicate": bool(previous), **record}

    def register_github_pull_request(self, case_id, revision, receipt):
        validated = FinOpsGitHubPullRequestReceipt.model_validate(receipt)
        record = self.store.get(f"finops-github-plan:{case_id}:{revision}")
        if not record or validated.plan_sha256 != record["plan_sha256"]:
            raise ValueError("El PR no corresponde al plan FinOps vigente.")
        plan = record["plan"]
        expected = {item["path"]: item["sha256"] for item in plan["files"]}
        actual = {item.get("path"): item.get("sha256") for item in validated.files}
        if (
            validated.repository_url != plan["repository_url"]
            or validated.branch != plan["branch"]
            or validated.base_branch != plan["base_branch"]
            or validated.base_commit != plan["base_commit"]
            or validated.pull_request_url
            != f"{plan['repository_url']}/pull/{validated.pull_request_number}"
            or actual != expected
        ):
            raise ValueError("El PR no contiene la publicación FinOps planificada.")
        payload = validated.model_dump(mode="json")
        key = f"finops-github-pr:{case_id}:{revision}"
        previous = self.store.get(key)
        if previous and previous != payload:
            raise ValueError("La revisión FinOps ya tiene otro PR.")
        if not previous:
            self.store.put(key, "finops_github_pr", payload)
            self.store.put(
                "finops-github-url:"
                + hashlib.sha256(validated.pull_request_url.encode()).hexdigest(),
                "finops_github_link",
                {
                    "case_id": case_id,
                    "revision": revision,
                    "url": validated.pull_request_url,
                    "kind": "pull_request",
                },
            )
        return {"duplicate": bool(previous), "receipt": payload}

    def prepare_engineering_issue(self, case_id, revision, engineer):
        intake = FinOpsIntake.model_validate(self.intakes.get(case_id, revision))
        issue = self.store.get(f"finops-issue:{case_id}:{revision}")
        plan = self.store.get(f"finops-github-plan:{case_id}:{revision}")
        merge = self.store.get(f"finops-github-merge:{case_id}:{revision}")
        workbook = self.store.get(f"finops-workbook-current:{case_id}:{revision}")
        if not issue or not plan or not merge or not workbook:
            raise ValueError("FinOps todavía no tiene publicación y merge completos.")
        publication = plan["plan"]
        decision = self.store.get(
            f"finops-decision:{case_id}:{revision}:{publication['decision_id']}"
        )
        analysis = self.result(case_id, revision)["analysis"]
        if (
            not decision
            or decision["contract_version"] != "1.1"
            or decision["decision"] != "approved"
            or not decision.get("authorization")
            or analysis["operational_status"] != "ready_for_decision"
            or not analysis["coverage"]["complete"]
            or analysis["budget_result"] == "not_evaluable"
            or workbook["status"] != "generated"
        ):
            raise ValueError(
                "La entrega a Ingeniería requiere evaluación completa y autorizada."
            )
        estimate_urls = sorted(
            {
                evidence["estimate_url"]
                for evidence in self._evidences(case_id, revision)
                if evidence.get("status") == "verified" and evidence.get("estimate_url")
            }
        )
        if not estimate_urls:
            raise ValueError("La entrega a Ingeniería requiere estimaciones verificadas.")
        manifest = next(
            item for item in publication["files"] if item["path"].endswith("manifest.json")
        )
        body = (
            f"FinOps completó la revisión {revision} del proyecto "
            f"`{intake.project_id}`.\n\n"
            f"Issue FinOps: {issue['issue_url']}\n\n"
            f"PR de costos: {merge['pull_request_url']}\n\n"
            f"Merge commit: `{merge['merge_commit_sha']}`\n\n"
            f"Arquitectura: {issue['architecture_issue_url']}\n\n"
            f"SHA-256 de Arquitectura: `{intake.handoff.artifact_sha256}`\n\n"
            f"AWS Pricing Calculator: {', '.join(estimate_urls)}\n\n"
            f"Forecast: `{workbook['relative_path']}` "
            f"(`{workbook['file_sha256']}`)\n\n"
            f"Resultado presupuestario: `{analysis['budget_result']}`."
        )
        issue_plan = EngineeringIssuePlan(
            case_id=case_id,
            project_id=intake.project_id,
            architecture_revision=revision,
            architecture_sha256=intake.handoff.artifact_sha256,
            repository_url=issue["repository_url"],
            finops_issue_url=issue["issue_url"],
            finops_pull_request_url=merge["pull_request_url"],
            finops_merge_commit_sha=merge["merge_commit_sha"],
            engineer_github_username=engineer,
            title=f"[Ingeniería] {intake.project_id} arquitectura y costos aprobados",
            body=body,
            body_sha256=hashlib.sha256(body.encode()).hexdigest(),
            labels=["engineering", "finops-approved"],
            assignees=[engineer],
        ).model_dump(mode="json")
        record = {"plan_sha256": self._digest(issue_plan), "plan": issue_plan}
        key = f"finops-engineering-issue-plan:{case_id}:{revision}"
        previous = self.store.get(key)
        if previous and previous != record:
            raise ValueError("El plan del issue de Ingeniería es inmutable.")
        if not previous:
            self.store.put(key, "finops_engineering_issue_plan", record)
            self.store.put(
                f"finops-engineering-manifest:{case_id}:{revision}",
                "finops_current",
                {"path": manifest["path"], "sha256": manifest["sha256"]},
            )
        return {"duplicate": bool(previous), **record}

    def register_engineering_issue(self, case_id, revision, receipt):
        validated = EngineeringIssueReceipt.model_validate(receipt)
        record = self.store.get(f"finops-engineering-issue-plan:{case_id}:{revision}")
        if not record:
            raise ValueError("Primero se debe preparar el issue de Ingeniería.")
        plan = record["plan"]
        if (
            validated.plan_sha256 != record["plan_sha256"]
            or validated.issue_url
            != f"{plan['repository_url']}/issues/{validated.issue_number}"
            or validated.body_sha256 != plan["body_sha256"]
            or validated.assignees != plan["assignees"]
        ):
            raise ValueError("El issue creado no corresponde al plan de Ingeniería.")
        payload = validated.model_dump(mode="json")
        key = f"finops-engineering-issue:{case_id}:{revision}"
        previous = self.store.get(key)
        if previous and previous != payload:
            raise ValueError("La revisión ya tiene otro issue de Ingeniería.")
        handoff_key = f"finops-engineering-handoff:{case_id}:{revision}"
        if not previous:
            self.store.put(key, "finops_engineering_issue", payload)
            handoff = self._build_engineering_handoff(case_id, revision, payload)
            self.store.put(
                handoff_key,
                "finops_engineering_handoff",
                handoff,
            )
            self.store.create_handoff(
                f"{case_id}:stage-4:stage-5:v{revision}",
                case_id,
                self.actor_id,
                "engineering-agent",
                "stage-4",
                "stage-5",
                revision=revision,
                artifact_sha256=handoff["forecast_sha256"],
            )
            self.store.event(
                f"finops-engineering-ready:{case_id}:{revision}",
                case_id,
                "finops.engineering_handoff_ready",
                {"revision": revision, "issue_url": validated.issue_url},
            )
        return {
            "duplicate": bool(previous),
            "receipt": payload,
            "handoff": self.store.get(handoff_key),
        }

    def _build_engineering_handoff(self, case_id, revision, issue_receipt):
        intake = FinOpsIntake.model_validate(self.intakes.get(case_id, revision))
        issue = self.store.get(f"finops-issue:{case_id}:{revision}")
        merge = self.store.get(f"finops-github-merge:{case_id}:{revision}")
        publication = self.store.get(f"finops-github-plan:{case_id}:{revision}")["plan"]
        workbook = self.store.get(f"finops-workbook-current:{case_id}:{revision}")
        analysis = self.result(case_id, revision)["analysis"]
        manifest = self.store.get(f"finops-engineering-manifest:{case_id}:{revision}")
        decision = self.store.get(
            f"finops-decision:{case_id}:{revision}:{publication['decision_id']}"
        )
        return FinOpsEngineeringHandoff(
            case_id=case_id,
            project_id=intake.project_id,
            architecture_revision=revision,
            architecture_sha256=intake.handoff.artifact_sha256,
            finops_issue_url=issue["issue_url"],
            engineering_issue_url=issue_receipt["issue_url"],
            finops_pull_request_url=merge["pull_request_url"],
            finops_merge_commit_sha=merge["merge_commit_sha"],
            estimate_urls=sorted(
                evidence["estimate_url"]
                for evidence in self._evidences(case_id, revision)
                if evidence.get("status") == "verified" and evidence.get("estimate_url")
            ),
            forecast_path=workbook["relative_path"],
            forecast_sha256=workbook["file_sha256"],
            manifest_path=manifest["path"],
            budget_result=analysis["budget_result"],
            decision_id=decision["decision_id"],
            authorization_id=decision["authorization"]["authorization_id"],
            created_at=datetime.fromtimestamp(self.store.clock(), timezone.utc),
        ).model_dump(mode="json")

    def get_engineering_handoff(self, case_id, revision):
        payload = self.store.get(f"finops-engineering-handoff:{case_id}:{revision}")
        if not payload:
            raise ValueError("La entrega a Ingeniería todavía no existe.")
        return FinOpsEngineeringHandoff.model_validate(payload).model_dump(mode="json")

    def accept_engineering_handoff(self, case_id, revision, receipt):
        validated = EngineeringHandoffAcceptance.model_validate(receipt)
        handoff = FinOpsEngineeringHandoff.model_validate(
            self.get_engineering_handoff(case_id, revision)
        )
        if (
            validated.case_id != case_id
            or validated.architecture_revision != revision
            or validated.architecture_sha256 != handoff.architecture_sha256
        ):
            raise ValueError("La aceptación corresponde a otra entrega de Ingeniería.")
        key = f"finops-engineering-acceptance:{case_id}:{revision}"
        payload = validated.model_dump(mode="json")
        previous = self.store.get(key)
        if previous and previous != payload:
            raise ValueError("La entrega ya tiene otra aceptación de Ingeniería.")
        if not previous:
            self.store.accept_handoff(
                f"{case_id}:stage-4:stage-5:v{revision}",
                validated.accepted_by,
                validated.accepted_at.timestamp(),
                acting_for="engineering-agent",
            )
            self.store.put(key, "finops_engineering_acceptance", payload)
            self.store.complete_phase(case_id, "stage-4")
            self.store.event(
                f"finops-engineering-accepted:{case_id}:{revision}",
                case_id,
                "finops.engineering_handoff_accepted",
                payload,
            )
        return {"duplicate": bool(previous), "acceptance": payload}

    def start_work(self, case_id, actor, actor_type):
        self.intakes.get(case_id, self._current_revision(case_id))
        return {
            "session_id": self.store.start_work(
                case_id, "stage-4", actor, actor_type
            )
        }

    def stop_work(self, session_id, actor):
        self.store.stop_work(session_id, actor)
        return {"session_id": session_id, "status": "closed"}

    def metrics(self, case_id):
        stored = self.store.metrics(case_id)
        phase = next(
            (item for item in stored["phases"] if item["phase"] == "stage-4"),
            None,
        )
        handoffs = [
            item
            for item in stored["handoffs"]
            if item["from_phase"] == "stage-4" and item["to_phase"] == "stage-5"
        ]
        return {
            "contract_version": "1.0",
            "case_id": case_id,
            "lead_time_seconds": phase["lead_seconds"] if phase else 0.0,
            "process_time_seconds": (
                phase["recorded_effort_seconds"]
                if phase
                else {"agent": 0.0, "human": 0.0}
            ),
            "wait_time_seconds": phase["unrecorded_or_wait_seconds"] if phase else 0.0,
            "in_progress": phase["in_progress"] if phase else True,
            "rework_cycles": stored["rework_cycles"],
            "engineering_handoffs": handoffs,
            "coverage": "recorded_intervals_only; no inferred activity from GitHub",
        }

    def observe_github_event(self, delivery_id, url, kind, action):
        link = self.store.get(
            "finops-github-url:" + hashlib.sha256(url.encode()).hexdigest()
        )
        if not link:
            return {"status": "unlinked", "transitioned": False}
        payload = {
            "delivery_id": delivery_id,
            "url": url,
            "event": kind,
            "action": action,
            "signature_verified": True,
            "transitioned": False,
        }
        self.store.event(
            f"finops-github-webhook:{delivery_id}:{link['case_id']}",
            link["case_id"],
            "finops.github_webhook_observed",
            payload,
        )
        return {"status": "linked", **payload, **link}

    def _current_revision(self, case_id):
        intakes = [
            item for item in self.store.list("finops_intake") if item["case_id"] == case_id
        ]
        if not intakes:
            raise ValueError("El expediente no tiene recepción FinOps.")
        return max(item["handoff"]["revision"] for item in intakes)

    def register_github_merge(self, case_id, revision, receipt):
        validated = FinOpsGitHubMergeReceipt.model_validate(receipt)
        plan = self.store.get(f"finops-github-plan:{case_id}:{revision}")
        pr = self.store.get(f"finops-github-pr:{case_id}:{revision}")
        if not plan or not pr:
            raise ValueError("Primero se debe registrar el PR FinOps.")
        expected = plan["plan"]
        if (
            validated.plan_sha256 != plan["plan_sha256"]
            or validated.authorization_id != expected["authorization_id"]
            or validated.repository_url != expected["repository_url"]
            or validated.pull_request_number != pr["pull_request_number"]
            or validated.pull_request_url != pr["pull_request_url"]
            or validated.head_sha != pr["commit_sha"]
            or validated.source_issue_url != expected["source_issue_url"]
        ):
            raise ValueError("El merge no corresponde al PR FinOps autorizado.")
        payload = validated.model_dump(mode="json")
        key = f"finops-github-merge:{case_id}:{revision}"
        previous = self.store.get(key)
        if previous and previous != payload:
            raise ValueError("La revisión FinOps ya tiene otro merge.")
        if not previous:
            self.store.put(key, "finops_github_merge", payload)
            self.store.event(key, case_id, "finops.github_pr_merged", payload)
        return {"duplicate": bool(previous), "receipt": payload}

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
            "workbook": self.store.get(
                f"finops-workbook-current:{case_id}:{revision}"
            ),
            "comment_drafts": [
                item
                for item in self.store.list("finops_comment_draft")
                if item["analysis_reference"]
                == (
                    self.store.get(self._analysis_pointer(case_id, revision)) or {}
                ).get("reference")
            ],
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
            "github_publication_plan": self.store.get(
                f"finops-github-plan:{case_id}:{revision}"
            ),
            "github_pull_request": self.store.get(
                f"finops-github-pr:{case_id}:{revision}"
            ),
            "github_merge": self.store.get(
                f"finops-github-merge:{case_id}:{revision}"
            ),
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
