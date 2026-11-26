"""FinOps MCP application and real STDIO protocol journey."""

import asyncio
import hashlib
import json
import os
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from openpyxl import load_workbook

from app.architecture.corrections import FinOpsCorrectionRequest
from app.architecture.demo import DEFAULT_INPUT
from app.architecture.models import ArchitectureFinOpsHandoff, ArchitecturePackage
from app.architecture.service import ArchitectureService
from app.delivery.engineering import EngineeringService
from app.delivery.engineering_models import EngineeringIntake, FinOpsEngineeringReceipt
from app.delivery.models import CaseReportRequest
from app.finops.evidence import PricingCalculatorEvidence
from app.finops.mcp_server import create_server
from app.finops.service import FinOpsService
from app.integrations.engineering_files import EngineeringFiles
from app.integrations.engineering_upstream import RecordedEngineeringSource
from app.integrations.langgraph import LangGraphExecution
from app.integrations.report_sources import CaseReportSources
from app.persistence.delivery import DeliveryConflict
from app.persistence.engineering import EngineeringRepository
from app.persistence.workflow import WorkflowStore
from app.workflow.graph import build_process_graph
from app.workflow.service import ProcessService
from app.workflow.state import initial_state

BACKEND = Path(__file__).resolve().parents[2]
REPOSITORY = Path(__file__).resolve().parents[4]
EVIDENCE = (
    REPOSITORY / "docs/evidence/agent4/block-c-s3/pricing-calculator-evidence.json"
)


def architecture_handoff():
    package = ArchitecturePackage.model_validate_json(DEFAULT_INPUT.read_text("utf-8"))
    sha256 = ArchitectureService.digest(package.model_dump(mode="json"))
    handoff = ArchitectureFinOpsHandoff(
        handoff_status="ready",
        revision=1,
        artifact_sha256=sha256,
        source_issue=package.source_issue,
        architecture_schema_version=package.schema_version,
        architecture=package,
        economic_contract=package.economic_contract,
        documents=sorted(package.artifacts()),
    )
    return handoff.model_dump(mode="json")


def service_at(tmp_path, handoff=None):
    database = f"sqlite:///{tmp_path / 'workflow.sqlite3'}"
    store = WorkflowStore(database)
    handoff = handoff or architecture_handoff()
    store.create_handoff(
        "block-c-s3:stage-3:stage-4:v1",
        "block-c-s3",
        "codex-cloud-architect",
        "finops-agent",
        "stage-3",
        "stage-4",
        revision=1,
        artifact_sha256=handoff["artifact_sha256"],
    )
    return (
        database,
        store,
        FinOpsService(store, output_dir=tmp_path / "artifacts"),
        handoff,
    )


def seed_finops_issue(store, service, handoff):
    repository_url = "https://github.com/example/project"
    issue_url = f"{repository_url}/issues/20"
    pull_request_url = f"{repository_url}/pull/19"
    merge_commit_sha = "b" * 40
    body = (
        f"Arquitectura aprobada: {pull_request_url}\n\n"
        f"Issue de Arquitectura: {handoff['source_issue']}\n\n"
        f"Merge commit: `{merge_commit_sha}`\n\n"
        f"Revisión: 1; artefacto: `{handoff['artifact_sha256']}`."
    )
    body_sha256 = hashlib.sha256(body.encode()).hexdigest()
    draft = {
        "repository_url": repository_url,
        "body": body,
        "body_sha256": body_sha256,
        "labels": ["finops", "architecture-approved"],
        "assignees": ["finops-owner"],
    }
    store.put(
        "architecture-finops-issue-draft:block-c-s3:1",
        "architecture_finops_issue_draft",
        draft,
    )
    store.put(
        "architecture-finops-issue:block-c-s3:1",
        "architecture_finops_issue",
        {
            "issue_url": issue_url,
            "issue_number": 20,
            "body_sha256": body_sha256,
        },
    )
    store.put(
        "architecture-github-approval:block-c-s3:1",
        "architecture_github_approval",
        {
            "pull_request_url": pull_request_url,
            "merge_commit_sha": merge_commit_sha,
        },
    )
    snapshot = {
        "repository_url": repository_url,
        "issue_url": issue_url,
        "issue_number": 20,
        "state": "open",
        "title": "[FinOps] project architecture v001",
        "body": body,
        "body_sha256": body_sha256,
        "labels": ["finops", "architecture-approved"],
        "assignees": ["finops-owner"],
        "observed_at": "2026-11-25T10:00:00-06:00",
        "architecture_revision": 1,
        "architecture_sha256": handoff["artifact_sha256"],
        "architecture_issue_url": handoff["source_issue"],
        "architecture_pull_request_url": pull_request_url,
        "architecture_merge_commit_sha": merge_commit_sha,
    }
    return service.register_issue("block-c-s3", 1, snapshot), snapshot


def decision_payload(reference, handoff, decision, decision_id):
    payload = {
        "decision_id": decision_id,
        "case_id": "block-c-s3",
        "project_id": handoff["architecture"]["project_id"],
        "architecture_revision": 1,
        "architecture_sha256": handoff["artifact_sha256"],
        "evaluation_reference": reference,
        "budget_result": "not_evaluable",
        "decision": decision,
        "rationale": "La cobertura económica sigue incompleta.",
        "decided_by": "finops-analyst",
        "decided_at": datetime.now(timezone.utc).isoformat(),
    }
    if decision == "approved":
        payload["authorization_reference"] = "github://reviews/finops-1"
    return payload


def test_finops_service_persists_partial_flow_decisions_and_correction(tmp_path):
    database, store, service, handoff = service_at(tmp_path)

    received = service.receive_handoff("block-c-s3", handoff)
    assert received["duplicate"] is False
    assert service.receive_handoff("block-c-s3", handoff)["duplicate"] is True
    assert service.prepare_calculator("block-c-s3", 1)["plan"]["status"] == "partial"
    evidence = json.loads(EVIDENCE.read_text("utf-8"))
    assert service.register_evidence("block-c-s3", 1, evidence)["duplicate"] is False
    assert service.register_evidence("block-c-s3", 1, evidence)["duplicate"] is True
    analysis = service.run_analysis("block-c-s3", 1)
    assert analysis["analysis"]["operational_status"] == "partial"
    assert analysis["analysis"]["budget_result"] == "not_evaluable"

    with pytest.raises(ValueError, match="evaluación económica incompleta"):
        service.decide(
            "block-c-s3",
            1,
            decision_payload(
                analysis["reference"], handoff, "approved", "decision-approved"
            ),
        )

    correction_decision = decision_payload(
        analysis["reference"],
        handoff,
        "architecture_correction_required",
        "decision-correction",
    )
    assert service.decide("block-c-s3", 1, correction_decision)["duplicate"] is False
    assert service.decide("block-c-s3", 1, correction_decision)["duplicate"] is True
    request = {
        "request_id": "finops-correction-kms-1",
        "architecture_id": "block-c-s3",
        "project_id": handoff["architecture"]["project_id"],
        "source_revision": 1,
        "reason": "KMS no tiene todavía una estimación verificable.",
        "affected_resources": ["documents-key"],
        "affected_dimensions": [
            {"resource_id": "documents-key", "dimension_id": "customer-key"},
            {
                "resource_id": "documents-key",
                "dimension_id": "symmetric-requests",
            },
        ],
        "requested_changes": [
            "Confirmar si KMS sigue siendo obligatorio y sus consumos aprobados."
        ],
        "new_constraints": ["No eliminar cifrado sin aprobación arquitectónica."],
        "finops_evaluation_reference": analysis["reference"],
        "requested_at": datetime.now(timezone.utc).isoformat(),
        "requested_by": "finops-agent",
        "origin": "finops",
    }
    correction = service.correction_request("block-c-s3", 1, request)
    FinOpsCorrectionRequest.model_validate(correction["request"])
    assert correction["handoff_to"] == "codex"
    assert correction["target_mcp"] == "aws_architecture"
    assert service.correction_request("block-c-s3", 1, request)["duplicate"] is True

    tampered = {**evidence, "architecture_revision": 2}
    with pytest.raises(ValueError, match="otra arquitectura o revisión"):
        service.register_evidence("block-c-s3", 1, tampered)
    store.engine.dispose()

    restarted_store = WorkflowStore(database)
    history = FinOpsService(restarted_store).history("block-c-s3", 1)
    assert history["current_analysis"]["analysis"]["operational_status"] == "partial"
    assert len(history["decisions"]) == 1
    assert len(history["corrections"]) == 1
    restarted_store.engine.dispose()


def test_dedicated_finops_server_exposes_only_finops_tools(tmp_path):
    _, store, service, _ = service_at(tmp_path)
    try:
        assert set(create_server(service)._tool_manager._tools) == {
            "recibir_handoff_arquitectura",
            "consultar_recepcion_finops",
            "validar_issue_finops",
            "preparar_plan_calculadora",
            "generar_estimacion_aws",
            "registrar_evidencia_calculadora",
            "ejecutar_analisis_finops",
            "consultar_resultado_finops",
            "generar_excel_costos",
            "preparar_comentario_finops",
            "emitir_decision_finops",
            "generar_solicitud_correccion_arquitectura",
            "preparar_devolucion_github",
            "registrar_devolucion_github",
            "preparar_publicacion_finops_github",
            "registrar_pr_finops_github",
            "registrar_merge_finops_github",
            "preparar_issue_ingenieria",
            "registrar_issue_ingenieria",
            "obtener_handoff_ingenieria",
            "registrar_aceptacion_handoff_ingenieria",
            "iniciar_trabajo_finops",
            "finalizar_trabajo_finops",
            "consultar_metricas_finops",
            "consultar_historial_finops",
        }
    finally:
        store.engine.dispose()


def test_finops_validates_issue_and_prepares_real_estimate_operation(tmp_path):
    _, store, service, handoff = service_at(tmp_path)
    try:
        service.receive_handoff("block-c-s3", handoff)
        registered, snapshot = seed_finops_issue(store, service, handoff)
        assert registered["duplicate"] is False
        assert service.register_issue("block-c-s3", 1, snapshot)["duplicate"] is True

        operation = service.generate_aws_estimate("block-c-s3", 1)
        assert operation["status"] == "awaiting_codex_execution"
        assert operation["calculator_url"] == "https://calculator.aws/"
        assert operation["may_mark_verified"] is False
        assert operation["plan"]["status"] == "partial"

        altered = {**snapshot, "architecture_sha256": "c" * 64}
        with pytest.raises(ValueError, match="no coincide"):
            service.register_issue("block-c-s3", 1, altered)
    finally:
        store.engine.dispose()


def test_finops_generates_one_versioned_workbook_and_comment_draft(tmp_path):
    _, store, service, handoff = service_at(tmp_path)
    try:
        service.receive_handoff("block-c-s3", handoff)
        seed_finops_issue(store, service, handoff)
        evidence = json.loads(EVIDENCE.read_text("utf-8"))
        service.register_evidence("block-c-s3", 1, evidence)
        analysis = service.run_analysis("block-c-s3", 1)

        generated = service.generate_workbook("block-c-s3", 1)
        duplicate = service.generate_workbook("block-c-s3", 1)
        assert generated["duplicate"] is False
        assert duplicate["duplicate"] is True
        artifact = generated["workbook"]
        assert artifact["status"] == "partial"
        assert artifact["pending_resources"] == ["documents-key"]
        path = tmp_path / "artifacts" / artifact["relative_path"]
        assert path.is_file()

        workbook = load_workbook(path, data_only=False)
        assert workbook.sheetnames == [
            "Resumen",
            "Costos",
            "Proyección",
            "Escenarios",
            "Evidencias",
            "Supuestos",
        ]
        assert workbook["Costos"]["E2"].value == "=D2*12"
        assert workbook["Costos"]["C3"].value == "Pendiente"
        assert workbook["Costos"]["D3"].value is None
        assert workbook["Proyección"]["N3"].value.startswith("=IF(COUNTA")
        assert workbook["Escenarios"]["B3"].value == "blocked"
        assert workbook["Evidencias"]["A2"].value == evidence["execution_id"]
        workbook.close()

        comment = service.prepare_comment(
            "block-c-s3",
            1,
            {
                "comment_id": "comment-kms-question",
                "comment_type": "question",
                "message": "Confirme los consumos mensuales de AWS KMS.",
                "architect_github_username": "cloud-architect",
            },
        )
        assert comment["comment"]["publication_status"] == "draft"
        assert comment["comment"]["body"].startswith("@cloud-architect")
        assert analysis["reference"] in comment["comment"]["body"]
        assert (
            service.prepare_comment(
                "block-c-s3",
                1,
                {
                    "comment_id": "comment-kms-question",
                    "comment_type": "question",
                    "message": "Confirme los consumos mensuales de AWS KMS.",
                    "architect_github_username": "cloud-architect",
                },
            )["duplicate"]
            is True
        )
    finally:
        store.engine.dispose()


def test_finops_prepares_and_registers_github_correction_without_duplicates(tmp_path):
    _, store, service, handoff = service_at(tmp_path)
    try:
        service.receive_handoff("block-c-s3", handoff)
        seed_finops_issue(store, service, handoff)
        service.register_evidence(
            "block-c-s3", 1, json.loads(EVIDENCE.read_text("utf-8"))
        )
        analysis = service.run_analysis("block-c-s3", 1)
        decision = decision_payload(
            analysis["reference"],
            handoff,
            "architecture_correction_required",
            "decision-github-correction",
        )
        service.decide("block-c-s3", 1, decision)
        request = {
            "request_id": "correction-github-kms",
            "architecture_id": "block-c-s3",
            "project_id": handoff["architecture"]["project_id"],
            "source_revision": 1,
            "reason": "KMS no tiene una estimación completa.",
            "affected_resources": ["documents-key"],
            "affected_dimensions": [
                {"resource_id": "documents-key", "dimension_id": "customer-key"}
            ],
            "requested_changes": ["Confirmar consumo y configuración de KMS."],
            "new_constraints": ["Conservar cifrado en reposo."],
            "finops_evaluation_reference": analysis["reference"],
            "requested_at": datetime.now(timezone.utc).isoformat(),
            "requested_by": "finops-agent",
            "origin": "finops",
        }
        service.correction_request("block-c-s3", 1, request)

        prepared = service.prepare_correction_github(
            "block-c-s3", 1, "correction-github-kms", "cloud-architect"
        )
        assert prepared["plan"]["close_with_label"] == "requiere-ajustes"
        assert prepared["plan"]["correction_issue_assignees"] == ["cloud-architect"]
        assert handoff["source_issue"] in prepared["plan"]["correction_issue_body"]
        receipt = {
            "plan_sha256": prepared["plan_sha256"],
            "finops_issue_url": prepared["plan"]["finops_issue_url"],
            "finops_issue_state": "closed",
            "finops_issue_labels": ["finops", "requiere-ajustes"],
            "finops_closing_comment_sha256": prepared["plan"]["closing_comment_sha256"],
            "correction_issue_url": "https://github.com/example/project/issues/21",
            "correction_issue_number": 21,
            "correction_issue_body_sha256": prepared["plan"][
                "correction_issue_body_sha256"
            ],
            "correction_issue_assignees": ["cloud-architect"],
            "executed_at": datetime.now(timezone.utc).isoformat(),
        }
        assert (
            service.register_correction_github(
                "block-c-s3", 1, "correction-github-kms", receipt
            )["duplicate"]
            is False
        )
        assert (
            service.register_correction_github(
                "block-c-s3", 1, "correction-github-kms", receipt
            )["duplicate"]
            is True
        )
    finally:
        store.engine.dispose()


def test_finops_blocks_cost_pr_while_evaluation_is_partial(tmp_path):
    _, store, service, handoff = service_at(tmp_path)
    try:
        service.receive_handoff("block-c-s3", handoff)
        seed_finops_issue(store, service, handoff)
        service.register_evidence(
            "block-c-s3", 1, json.loads(EVIDENCE.read_text("utf-8"))
        )
        analysis = service.run_analysis("block-c-s3", 1)
        service.generate_workbook("block-c-s3", 1)
        decision = decision_payload(
            analysis["reference"],
            handoff,
            "information_required",
            "decision-partial-information",
        )
        service.decide("block-c-s3", 1, decision)
        with pytest.raises(ValueError, match="evaluación completa y autorizada"):
            service.prepare_github_publication(
                "block-c-s3", 1, "decision-partial-information"
            )
    finally:
        store.engine.dispose()


def test_finops_delivers_merged_costs_to_engineering_and_measures_work(
    tmp_path, monkeypatch
):
    # A complete S3-only fixture exercises the actual publication generators. No
    # calculator, GitHub, model, Terraform or emulator is called by this journey.
    payload = architecture_handoff()["architecture"]
    payload["resources"] = [{**payload["resources"][0], "dependencies": []}]
    payload["cost_assumptions"] = payload["cost_assumptions"][:1]
    payload["economic_contract"]["pricing_inputs"] = payload["economic_contract"][
        "pricing_inputs"
    ][:1]
    payload["missing_baselines"] = []
    payload["open_questions"] = []
    package = ArchitecturePackage.model_validate(payload)
    arch_sha = ArchitectureService.digest(package.model_dump(mode="json"))
    handoff = ArchitectureFinOpsHandoff(
        handoff_status="ready",
        revision=1,
        artifact_sha256=arch_sha,
        source_issue=package.source_issue,
        architecture_schema_version=package.schema_version,
        architecture=package,
        economic_contract=package.economic_contract,
        documents=sorted(package.artifacts()),
    ).model_dump(mode="json")
    database, store, service, handoff = service_at(tmp_path, handoff)
    case = "block-c-s3"
    repository = "https://github.com/example/project"
    now = datetime.now(timezone.utc).isoformat()
    try:
        store.register_project(
            case,
            package.project_id,
            "Fixture S3",
            "Cliente ficticio",
            "engineer",
            is_fictitious=True,
        )
        store.put(f"owner:{case}", "owner", {"manager_id": "engineer"})
        execution = LangGraphExecution(build_process_graph(InMemorySaver()))
        execution.start(
            f"process:{case}",
            {
                **initial_state(case, "engineer"),
                "stage": 3,
                "status": "awaiting_deliverable",
            },
        )
        process = ProcessService(execution, store, "engineer")
        process.ensure(case)
        process.internal(
            case,
            "architecture-ready",
            "deliverable.ready",
            revision=1,
            artifact_sha256=arch_sha,
            evidence=[package.source_issue],
        )
        process.internal(
            case,
            "architecture-approved",
            "stage.approved",
            revision=1,
            artifact_sha256=arch_sha,
            evidence=[package.source_issue],
        )
        state = {
            "status": "ready_for_finops",
            "revision": 1,
            "artifact_sha256": arch_sha,
            "package": package.model_dump(mode="json"),
            "documents": package.artifacts(),
        }
        architecture = ArchitectureService(
            SimpleNamespace(inspect=lambda _: SimpleNamespace(state=state, pending=[])),
            None,
            store=store,
        )
        store.put(
            f"architecture-project-context:{case}",
            "architecture_project_context",
            {
                "repository_url": repository,
                "architecture_issue_url": package.source_issue,
                "source_commit": "a" * 40,
                "architect": "architect",
            },
        )
        arch_plan = architecture.prepare_github_publication(case)
        architecture.register_github_pull_request(
            case,
            {
                "plan_sha256": arch_plan["plan_sha256"],
                "repository_url": repository,
                "branch": arch_plan["plan"]["branch"],
                "base_branch": "main",
                "base_commit": "a" * 40,
                "commit_sha": "c" * 40,
                "files": [
                    {"path": f["path"], "sha256": f["sha256"]}
                    for f in arch_plan["plan"]["files"]
                ],
                "pull_request_number": 19,
                "pull_request_url": repository + "/pull/19",
                "requested_reviewers": ["architect"],
                "state": "open",
                "created_at": now,
            },
        )
        service.receive_handoff(case, handoff)
        seed_finops_issue(store, service, handoff)
        # seed_finops_issue provides a minimal approval for other FinOps journeys;
        # this cross-component journey supplies the complete typed GitHub receipt.
        checks = [
            {
                "name": "offline checks",
                "status": "completed",
                "conclusion": "success",
                "details_url": repository + "/actions/runs/1",
            }
        ]
        store.put(
            f"architecture-github-approval:{case}:1",
            "architecture_github_approval",
            {
                "contract_version": "1.0",
                "plan_sha256": arch_plan["plan_sha256"],
                "repository_url": repository,
                "pull_request_number": 19,
                "pull_request_url": repository + "/pull/19",
                "head_sha": "c" * 40,
                "decision": "approved",
                "reviewer": "architect",
                "review_id": "123",
                "reviewed_at": now,
                "checks": checks,
                "pull_request_state": "closed",
                "merged": True,
                "merged_at": now,
                "merge_commit_sha": "b" * 40,
                "source_issue_url": package.source_issue,
                "source_issue_state": "closed",
                "source_issue_closed_at": now,
                "evidence_source": "github_mcp",
                "observed_at": now,
                "github_delivery_id": None,
                "webhook_signature_verified": False,
            },
        )
        evidence = json.loads(EVIDENCE.read_text("utf-8"))
        evidence["architecture_sha256"] = arch_sha
        evidence["execution_id"] = PricingCalculatorEvidence.make_execution_id(
            arch_sha,
            evidence["resource_id"],
            evidence["region"],
            evidence["parameters"],
        )
        service.register_evidence(case, 1, evidence)
        analysis = service.run_analysis(case, 1)
        assert analysis["analysis"]["coverage"]["complete"]
        service.generate_workbook(case, 1)
        decision = {
            "contract_version": "1.1",
            "decision_id": "decision-engineering-ready",
            "case_id": case,
            "project_id": package.project_id,
            "architecture_revision": 1,
            "architecture_sha256": arch_sha,
            "evaluation_reference": analysis["reference"],
            "budget_result": "within_budget",
            "decision": "approved",
            "rationale": "Decisión explícita del fixture de integración.",
            "decided_by": "finops-analyst",
            "decided_at": now,
            "authorization": {
                "authorization_id": "authorization-engineering-ready",
                "case_id": case,
                "project_id": package.project_id,
                "architecture_revision": 1,
                "architecture_sha256": arch_sha,
                "evaluation_reference": analysis["reference"],
                "authorized_by": "finops-analyst",
                "authorized_at": now,
                "conversation_reference": "codex://threads/finops-engineering",
                "statement_sha256": "d" * 64,
            },
        }
        service.decide(case, 1, decision)
        publication = service.prepare_github_publication(
            case, 1, decision["decision_id"]
        )
        service.register_github_pull_request(
            case,
            1,
            {
                "plan_sha256": publication["plan_sha256"],
                "repository_url": repository,
                "branch": publication["plan"]["branch"],
                "base_branch": "main",
                "base_commit": "b" * 40,
                "commit_sha": "e" * 40,
                "files": [
                    {"path": f["path"], "sha256": f["sha256"]}
                    for f in publication["plan"]["files"]
                ],
                "pull_request_number": 20,
                "pull_request_url": repository + "/pull/20",
                "state": "open",
                "created_at": now,
            },
        )
        service.register_github_merge(
            case,
            1,
            {
                "plan_sha256": publication["plan_sha256"],
                "authorization_id": "authorization-engineering-ready",
                "repository_url": repository,
                "pull_request_number": 20,
                "pull_request_url": repository + "/pull/20",
                "head_sha": "e" * 40,
                "checks": checks,
                "pull_request_state": "closed",
                "merged": True,
                "merged_at": now,
                "merge_commit_sha": "1" * 40,
                "source_issue_url": repository + "/issues/20",
                "source_issue_state": "closed",
                "source_issue_closed_at": now,
                "observed_at": now,
            },
        )
        work = service.start_work(case, "finops-agent", "agent")
        service.stop_work(work["session_id"], "finops-agent")
        plan = service.prepare_engineering_issue(case, 1, "infrastructure-engineer")
        registered = service.register_engineering_issue(
            case,
            1,
            {
                "plan_sha256": plan["plan_sha256"],
                "issue_url": repository + "/issues/22",
                "issue_number": 22,
                "body_sha256": plan["plan"]["body_sha256"],
                "assignees": ["infrastructure-engineer"],
                "created_at": now,
            },
        )
        engineering = EngineeringService(
            EngineeringRepository(store),
            EngineeringFiles(tmp_path / "unused"),
            "engineer",
            upstream=RecordedEngineeringSource(store),
            process=process,
        )
        receipt = FinOpsEngineeringReceipt(
            intake_id=uuid4(),
            case_id=case,
            revision=1,
            modules=[
                {
                    "repository": b.repository.removeprefix(
                        "https://github.com/"
                    ).removesuffix(".git"),
                    "path": "aws/" + b.module_id,
                    "commit": b.commit,
                    "approved_by": "baseline-reviewer",
                    "approval_reference": "https://github.com/marcor0311/aws-cloud-consultant-baseline-modules/pull/1#pullrequestreview-1",
                }
                for b in package.baselines
            ],
        )
        altered = deepcopy(publication)
        altered["plan"]["files"][0]["content"] += "corrupt"
        store.put(f"finops-github-plan:{case}:1", "finops_github_plan", altered)
        with pytest.raises(DeliveryConflict):
            engineering.receive_finops(receipt)
        assert process.get(case)["state"]["stage"] == 4
        store.put(f"finops-github-plan:{case}:1", "finops_github_plan", publication)
        register = engineering.repository.register
        with monkeypatch.context() as patch:

            def interrupted(*args, **kwargs):
                raise RuntimeError("Interrupted after process checkpoint")

            patch.setattr(engineering.repository, "register", interrupted)
            with pytest.raises(RuntimeError, match="Interrupted"):
                engineering.receive_finops(receipt)
        assert engineering.repository.register == register
        assert process.get(case)["state"]["stage"] == 5
        received = engineering.receive_finops(receipt)
        assert received["upstream_current"] is True
        assert received["intake"]["input"]["finops_architecture_sha256"] == arch_sha
        assert received["intake"]["input"]["schema_version"] == "1.1"
        normalized = EngineeringIntake.model_validate(received["intake"]["input"])
        assert normalized.approval_digest(3) == arch_sha
        assert normalized.approval_digest(4) == registered["handoff"]["forecast_sha256"]
        assert (
            received["intake"]["input"]["finops"]["approval"]["actor"]
            == "finops-analyst"
        )
        assert process.get(case)["state"]["stage"] == 5
        assert engineering.receive_finops(receipt)["intake"] == received["intake"]
        acceptance = received["intake"]["finops_acceptance"]
        assert (
            service.accept_engineering_handoff(case, 1, acceptance)["duplicate"] is True
        )
        assert (
            acceptance["architecture_sha256"]
            == registered["handoff"]["architecture_sha256"]
        )
        for file in received["intake"]["files"]:
            assert (
                hashlib.sha256(
                    engineering.read_file(receipt.intake_id, file["sha256"])
                ).hexdigest()
                == file["sha256"]
            )
        sources = CaseReportSources(store, None, engineering).capture(
            CaseReportRequest(
                report_id=uuid4(), case_id=case, intake_id=receipt.intake_id
            ),
            "engineer",
        )
        assert (
            sources["engineering"]["intake"]["upstream_source"]
            == received["intake"]["upstream_source"]
        )
        assert sources["closure_blockers"]
        metrics = service.metrics(case)
        assert metrics["in_progress"] is False
        assert metrics["process_time_seconds"]["agent"] >= 0
        assert metrics["engineering_handoffs"][0]["pending_acceptance"] is False
        # A changed source cannot silently stay approved after restart/recapture.
        store.put(
            f"finops-workbook-current:{case}:1",
            "finops_current",
            {**store.get(f"finops-workbook-current:{case}:1"), "file_sha256": "0" * 64},
        )
        assert engineering.get(receipt.intake_id)["upstream_current"] is False
        store.engine.dispose()
        restarted_store = WorkflowStore(database)
        restarted = FinOpsService(restarted_store, output_dir=tmp_path / "artifacts")
        assert restarted.get_engineering_handoff(case, 1) == registered["handoff"]
        assert restarted.metrics(case)["in_progress"] is False
        restarted_store.engine.dispose()
    finally:
        store.engine.dispose()


async def protocol_exchange(database, handoff):
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.finops.mcp_server"],
        cwd=str(BACKEND),
        env={
            **os.environ,
            "FINOPS_DATABASE_URL": database,
            "LANGSMITH_TRACING": "false",
            "LANGCHAIN_TRACING_V2": "false",
        },
    )
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            initialized = await session.initialize()
            tools = await session.list_tools()
            result = await session.call_tool(
                "recibir_handoff_arquitectura",
                {"expediente_id": "block-c-s3", "handoff": handoff},
            )
            return initialized, tools, result


async def protocol_issue_and_estimate_exchange(database, snapshot):
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.finops.mcp_server"],
        cwd=str(BACKEND),
        env={
            **os.environ,
            "FINOPS_DATABASE_URL": database,
            "LANGSMITH_TRACING": "false",
            "LANGCHAIN_TRACING_V2": "false",
        },
    )
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            validated = await session.call_tool(
                "validar_issue_finops",
                {
                    "expediente_id": "block-c-s3",
                    "revision": 1,
                    "issue": snapshot,
                },
            )
            operation = await session.call_tool(
                "generar_estimacion_aws",
                {"expediente_id": "block-c-s3", "revision": 1},
            )
            return validated, operation


async def protocol_workbook_and_comment_exchange(database, data_dir):
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.finops.mcp_server"],
        cwd=str(BACKEND),
        env={
            **os.environ,
            "FINOPS_DATABASE_URL": database,
            "FINOPS_DATA_DIR": str(data_dir),
            "LANGSMITH_TRACING": "false",
            "LANGCHAIN_TRACING_V2": "false",
        },
    )
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            workbook = await session.call_tool(
                "generar_excel_costos",
                {"expediente_id": "block-c-s3", "revision": 1},
            )
            comment = await session.call_tool(
                "preparar_comentario_finops",
                {
                    "expediente_id": "block-c-s3",
                    "revision": 1,
                    "solicitud": {
                        "comment_id": "comment-protocol-kms",
                        "comment_type": "question",
                        "message": "Confirme los consumos mensuales de AWS KMS.",
                        "architect_github_username": "cloud-architect",
                    },
                },
            )
            return workbook, comment


def test_real_stdio_protocol_initializes_lists_and_calls_tool(tmp_path):
    database, store, _, handoff = service_at(tmp_path)
    store.engine.dispose()

    initialized, tools, result = asyncio.run(protocol_exchange(database, handoff))

    assert initialized.server_info.name == "Cloud FinOps Agent"
    assert initialized.protocol_version
    assert {item.name for item in tools.tools} >= {
        "recibir_handoff_arquitectura",
        "validar_issue_finops",
        "generar_estimacion_aws",
        "generar_excel_costos",
        "preparar_comentario_finops",
        "preparar_devolucion_github",
        "registrar_devolucion_github",
        "preparar_publicacion_finops_github",
        "registrar_pr_finops_github",
        "registrar_merge_finops_github",
        "preparar_issue_ingenieria",
        "registrar_issue_ingenieria",
        "obtener_handoff_ingenieria",
        "registrar_aceptacion_handoff_ingenieria",
        "iniciar_trabajo_finops",
        "finalizar_trabajo_finops",
        "consultar_metricas_finops",
        "ejecutar_analisis_finops",
        "emitir_decision_finops",
    }
    assert result.is_error is False
    assert result.structured_content["duplicate"] is False
    assert result.structured_content["intake"]["operational_status"] == "received"


def test_real_stdio_protocol_validates_issue_and_prepares_estimate(tmp_path):
    database, store, service, handoff = service_at(tmp_path)
    service.receive_handoff("block-c-s3", handoff)
    _, snapshot = seed_finops_issue(store, service, handoff)
    store.engine.dispose()

    validated, operation = asyncio.run(
        protocol_issue_and_estimate_exchange(database, snapshot)
    )

    assert validated.is_error is False
    assert validated.structured_content is not None, validated.model_dump()
    assert validated.structured_content["duplicate"] is True
    assert operation.is_error is False
    assert operation.structured_content is not None, operation.model_dump()
    assert operation.structured_content["status"] == "awaiting_codex_execution"
    assert operation.structured_content["may_mark_verified"] is False


def test_real_stdio_protocol_generates_workbook_and_comment(tmp_path):
    database, store, service, handoff = service_at(tmp_path)
    service.receive_handoff("block-c-s3", handoff)
    seed_finops_issue(store, service, handoff)
    service.register_evidence("block-c-s3", 1, json.loads(EVIDENCE.read_text("utf-8")))
    service.run_analysis("block-c-s3", 1)
    store.engine.dispose()

    workbook, comment = asyncio.run(
        protocol_workbook_and_comment_exchange(database, tmp_path / "mcp-data")
    )

    assert workbook.is_error is False
    assert workbook.structured_content["workbook"]["status"] == "partial"
    relative = workbook.structured_content["workbook"]["relative_path"]
    assert (tmp_path / "mcp-data" / "artifacts" / relative).is_file()
    assert comment.is_error is False
    assert comment.structured_content["comment"]["publication_status"] == "draft"
