"""Read the recorded Architecture/FinOps publications without rewriting approvals."""

import base64
import json
from hashlib import sha256

from app.architecture.github_delivery import (
    GitHubApprovalReceipt,
    GitHubPublicationPlan,
    GitHubPullRequestReceipt,
)
from app.architecture.service import ArchitectureService
from app.delivery.engineering_models import EngineeringIntake, digest
from app.finops.analysis import FinOpsEconomicAnalysis
from app.finops.engineering_delivery import FinOpsEngineeringHandoff
from app.finops.github_delivery import (
    FinOpsGitHubMergeReceipt,
    FinOpsGitHubPublicationPlan,
    FinOpsGitHubPullRequestReceipt,
)
from app.finops.models import FinOpsEvaluationDecision, FinOpsIntake
from app.persistence.delivery import DeliveryConflict


class RecordedEngineeringSource:
    def __init__(self, store):
        self.store = store

    def resolve(self, receipt):
        """Normalize original bytes and bind all original receipts to the intake."""
        try:
            return self._resolve(receipt)
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise DeliveryConflict(
                f"Entrega FinOps incompleta o inválida: {error}"
            ) from error

    def _resolve(self, receipt):
        case, revision = receipt.case_id, receipt.revision
        records = {}

        def read(prefix):
            key = f"{prefix}:{case}:{revision}"
            value = self.store.get(key)
            if not value:
                raise DeliveryConflict(f"Falta el registro de origen {prefix}")
            records[key] = value
            return value

        handoff = FinOpsEngineeringHandoff.model_validate(
            read("finops-engineering-handoff")
        )
        intake = FinOpsIntake.model_validate(read("finops-intake"))
        architecture = intake.handoff.architecture
        arch_record = read("architecture-github-plan")
        arch_plan = GitHubPublicationPlan.model_validate(arch_record["plan"])
        arch_pr = GitHubPullRequestReceipt.model_validate(
            read("architecture-github-pr")
        )
        arch_approval = GitHubApprovalReceipt.model_validate(
            read("architecture-github-approval")
        )
        finops_record = read("finops-github-plan")
        finops_plan = FinOpsGitHubPublicationPlan.model_validate(finops_record["plan"])
        finops_pr = FinOpsGitHubPullRequestReceipt.model_validate(
            read("finops-github-pr")
        )
        merge = FinOpsGitHubMergeReceipt.model_validate(read("finops-github-merge"))
        decision_key = f"finops-decision:{case}:{revision}:{handoff.decision_id}"
        decision_raw = self.store.get(decision_key)
        if not decision_raw:
            raise DeliveryConflict("Falta la decisión FinOps original")
        records[decision_key] = decision_raw
        decision = FinOpsEvaluationDecision.model_validate(decision_raw)
        analysis_record = read("finops-current-analysis")
        analysis = FinOpsEconomicAnalysis.model_validate(analysis_record["analysis"])
        workbook = read("finops-workbook-current")

        arch_sha = ArchitectureService.digest(architecture.model_dump(mode="json"))
        repository = arch_plan.repository_url
        if (
            intake.case_id != case
            or handoff.case_id != case
            or handoff.project_id != intake.project_id
            or arch_plan.case_id != case
            or arch_plan.project_id != intake.project_id
            or arch_plan.revision != revision
            or intake.handoff.revision != revision
            or handoff.architecture_revision != revision
            or intake.handoff.artifact_sha256 != arch_sha
            or handoff.architecture_sha256 != arch_sha
            or arch_plan.artifact_sha256 != arch_sha
        ):
            raise DeliveryConflict(
                "El handoff altera la identidad o hash de Arquitectura"
            )
        for record, plan, pr, approval in (
            (arch_record, arch_plan, arch_pr, arch_approval),
            (finops_record, finops_plan, finops_pr, merge),
        ):
            plan_hash = ArchitectureService.digest(record["plan"])
            if (
                record["plan_sha256"] != plan_hash
                or pr.plan_sha256 != plan_hash
                or approval.plan_sha256 != plan_hash
                or plan.repository_url != repository
                or pr.repository_url != repository
                or approval.repository_url != repository
                or pr.branch != plan.branch
                or pr.base_commit != plan.base_commit
                or pr.files
                != [{"path": f.path, "sha256": f.sha256} for f in plan.files]
                or approval.head_sha != pr.commit_sha
                or approval.pull_request_url != pr.pull_request_url
                or approval.pull_request_number != pr.pull_request_number
                or pr.pull_request_url != f"{repository}/pull/{pr.pull_request_number}"
                or approval.source_issue_url != plan.source_issue_url
            ):
                raise DeliveryConflict(
                    "La publicación no coincide con sus recibos GitHub"
                )
        if arch_approval.reviewer.casefold() != arch_plan.required_reviewer.casefold():
            raise DeliveryConflict(
                "La aprobación no corresponde al arquitecto requerido"
            )
        authorization = decision.authorization
        if (
            finops_plan.case_id != case
            or finops_plan.project_id != intake.project_id
            or finops_plan.architecture_revision != revision
            or finops_plan.architecture_sha256 != arch_sha
            or finops_plan.base_commit != arch_approval.merge_commit_sha
            or decision.contract_version != "1.1"
            or decision.decision != "approved"
            or not authorization
            or authorization.authorized_by != decision.decided_by
            or authorization.authorization_id != handoff.authorization_id
            or merge.authorization_id != handoff.authorization_id
            or finops_plan.authorization_id != handoff.authorization_id
            or finops_plan.decision_id != handoff.decision_id
            or decision.case_id != case
            or decision.project_id != intake.project_id
            or decision.architecture_revision != revision
            or decision.architecture_sha256 != arch_sha
            or decision.evaluation_reference != analysis_record["reference"]
            or analysis.case_id != case
            or analysis.project_id != intake.project_id
            or analysis.architecture_revision != revision
            or analysis.architecture_sha256 != arch_sha
            or analysis.operational_status != "ready_for_decision"
            or not analysis.coverage.complete
            or analysis.budget_comparison.status != "comparable"
            or analysis.budget_result not in ("within_budget", "near_limit")
            or handoff.budget_result != analysis.budget_result
            or decision.budget_result != analysis.budget_result
            or handoff.finops_merge_commit_sha != merge.merge_commit_sha
            or handoff.finops_pull_request_url != merge.pull_request_url
            or handoff.finops_issue_url != finops_plan.source_issue_url
            or workbook["status"] != "generated"
            or workbook["relative_path"] != handoff.forecast_path
            or workbook["file_sha256"] != handoff.forecast_sha256
        ):
            raise DeliveryConflict(
                "FinOps requiere evaluación vigente completa, dentro del presupuesto y autorizada"
            )
        expected_modules = sorted(
            (
                b.repository.removeprefix("https://github.com/").removesuffix(".git"),
                f"aws/{b.module_id}",
                b.commit,
            )
            for b in architecture.baselines
        )
        if (
            sorted((m.repository, m.path, m.commit) for m in receipt.modules)
            != expected_modules
        ):
            raise DeliveryConflict(
                "Los módulos no corresponden a la selección exacta de Arquitectura"
            )

        files = []

        def package(plan, commit, roles):
            refs = []
            for file in plan.files:
                raw = (
                    file.content.encode()
                    if file.encoding == "utf-8"
                    else base64.b64decode(file.content, validate=True)
                )
                ref = {
                    "role": roles.get(
                        file.path.rsplit("/", 1)[-1], "upstream_artifact"
                    ),
                    "path": file.path,
                    "sha256": file.sha256,
                    "reference": f"{repository}/blob/{commit}/{file.path}",
                }
                refs.append(ref)
                files.append((ref, raw))
                if (
                    len(raw) > 16 * 1024 * 1024
                    or sum(len(data) for _, data in files) > 64 * 1024 * 1024
                ):
                    raise DeliveryConflict(
                        "El paquete supera los límites de archivo o recepción"
                    )
            return refs

        arch_files = package(
            arch_plan,
            arch_approval.merge_commit_sha,
            {
                "requirements.md": "requirements",
                "architecture.md": "design",
                "security.md": "policies",
            },
        )
        finops_files = package(
            finops_plan,
            merge.merge_commit_sha,
            {
                "forecast.xlsx": "cost_workbook",
                "pricing-evidence.json": "pricing_evidence",
            },
        )
        raw_by_path = {ref["path"]: raw for ref, raw in files}
        prefix = f"docs/03-architecture/versions/v{revision:03d}"
        if json.loads(
            raw_by_path[f"{prefix}/architecture-package.json"]
        ) != architecture.model_dump(mode="json"):
            raise DeliveryConflict("La publicación altera el paquete de Arquitectura")
        for name, raw in architecture.artifacts().items():
            if raw_by_path.get(f"{prefix}/{name}") != raw.encode():
                raise DeliveryConflict(
                    "Los documentos no derivan de la arquitectura aprobada"
                )
        if (
            sha256(raw_by_path.get(handoff.forecast_path, b"")).hexdigest()
            != handoff.forecast_sha256
        ):
            raise DeliveryConflict("El forecast publicado no coincide con el handoff")
        finops_prefix = f"docs/04-finops/versions/v{revision:03d}"
        if json.loads(raw_by_path[f"{finops_prefix}/analysis.json"]) != analysis_record:
            raise DeliveryConflict("El análisis publicado ya no es el vigente")
        manifest = json.loads(raw_by_path[handoff.manifest_path])
        if (
            manifest["architecture_sha256"] != arch_sha
            or manifest["decision_id"] != handoff.decision_id
            or manifest["authorization_id"] != handoff.authorization_id
            or manifest["files"]
            != [
                {"path": f.path.rsplit("/", 1)[-1], "sha256": f.sha256}
                for f in finops_plan.files
                if f.path != handoff.manifest_path
            ]
        ):
            raise DeliveryConflict("El manifiesto FinOps no coincide con sus archivos")
        evidence = json.loads(raw_by_path[f"{finops_prefix}/pricing-evidence.json"])
        estimates = sorted(
            {
                e["estimate_url"]
                for e in evidence
                if e.get("status") == "verified" and e.get("estimate_url")
            }
        )
        if sorted(set(handoff.estimate_urls)) != estimates:
            raise DeliveryConflict(
                "Las estimaciones no corresponden a la evidencia publicada"
            )
        handoff_id = f"{case}:stage-4:stage-5:v{revision}"
        incoming = self.store.handoff(handoff_id)
        if not incoming or (
            incoming["case_id"],
            incoming["from_phase"],
            incoming["to_phase"],
            incoming["to_actor"],
            incoming["from_actor"],
            incoming["revision"],
            incoming["artifact_sha256"],
        ) != (
            case,
            "stage-4",
            "stage-5",
            "engineering-agent",
            intake.acceptance.accepted_by,
            revision,
            handoff.forecast_sha256,
        ):
            raise DeliveryConflict(
                "La entrega persistida no corresponde al handoff FinOps"
            )
        budget = analysis.budget_comparison.budget
        request = EngineeringIntake(
            schema_version="1.1",
            intake_id=receipt.intake_id,
            case_id=case,
            incoming_handoff_id=handoff_id,
            repository=repository.removeprefix("https://github.com/"),
            architecture={
                "commit": arch_approval.merge_commit_sha,
                "revision": revision,
                "files": arch_files,
                "approval": {
                    "event_id": f"architecture-github-approved:{case}:{revision}",
                    "actor": arch_approval.reviewer,
                    "reference": f"{arch_approval.pull_request_url}#pullrequestreview-{arch_approval.review_id}",
                },
            },
            finops={
                "commit": merge.merge_commit_sha,
                "revision": revision,
                "files": finops_files,
                "approval": {
                    "event_id": decision_key,
                    "actor": decision.decided_by,
                    "reference": merge.pull_request_url,
                },
            },
            finops_architecture_commit=arch_approval.merge_commit_sha,
            finops_architecture_sha256=arch_sha,
            modules=receipt.modules,
            region=architecture.region,
            budget=budget.amount,
            estimate=analysis.verified_monthly_subtotal
            if budget.period == "month"
            else analysis.verified_annual_subtotal,
            currency=budget.currency,
            period=budget.period,
            calculator_url=estimates[0],
        )
        record_hashes = {key: digest(value) for key, value in records.items()}
        binding = {
            "kind": "recorded_finops_v1",
            "records": record_hashes,
            "sha256": digest(record_hashes),
            "architecture_approval": arch_approval.model_dump(mode="json"),
            "finops_decision": decision.model_dump(mode="json"),
            "finops_merge": merge.model_dump(mode="json"),
        }
        return request, binding, files, incoming

    def validate(self, request, binding):
        from app.delivery.engineering_models import FinOpsEngineeringReceipt

        current, source, files, incoming = self.resolve(
            FinOpsEngineeringReceipt(
                intake_id=request.intake_id,
                case_id=request.case_id,
                revision=request.finops.revision,
                modules=request.modules,
            )
        )
        if current != request or source != binding:
            raise DeliveryConflict(
                "Los registros de origen cambiaron desde la recepción"
            )
        return files, incoming
