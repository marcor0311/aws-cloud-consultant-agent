"""FinOps MCP application and real STDIO protocol journey."""

import asyncio
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from openpyxl import load_workbook

from app.architecture.corrections import FinOpsCorrectionRequest
from app.architecture.demo import DEFAULT_INPUT
from app.architecture.models import ArchitectureFinOpsHandoff, ArchitecturePackage
from app.architecture.service import ArchitectureService
from app.finops.mcp_server import create_server
from app.finops.service import FinOpsService
from app.persistence.workflow import WorkflowStore

BACKEND = Path(__file__).resolve().parents[2]
REPOSITORY = Path(__file__).resolve().parents[4]
EVIDENCE = (
    REPOSITORY
    / "docs/evidence/agent4/block-c-s3/pricing-calculator-evidence.json"
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


def service_at(tmp_path):
    database = f"sqlite:///{tmp_path / 'workflow.sqlite3'}"
    store = WorkflowStore(database)
    handoff = architecture_handoff()
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
    return database, store, FinOpsService(store, output_dir=tmp_path / "artifacts"), handoff


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
        assert service.prepare_comment(
            "block-c-s3",
            1,
            {
                "comment_id": "comment-kms-question",
                "comment_type": "question",
                "message": "Confirme los consumos mensuales de AWS KMS.",
                "architect_github_username": "cloud-architect",
            },
        )["duplicate"] is True
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
    service.register_evidence(
        "block-c-s3", 1, json.loads(EVIDENCE.read_text("utf-8"))
    )
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
