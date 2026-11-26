"""FinOps MCP application and real STDIO protocol journey."""

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

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
    return database, store, FinOpsService(store), handoff


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
            "preparar_plan_calculadora",
            "registrar_evidencia_calculadora",
            "ejecutar_analisis_finops",
            "consultar_resultado_finops",
            "emitir_decision_finops",
            "generar_solicitud_correccion_arquitectura",
            "consultar_historial_finops",
        }
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


def test_real_stdio_protocol_initializes_lists_and_calls_tool(tmp_path):
    database, store, _, handoff = service_at(tmp_path)
    store.engine.dispose()

    initialized, tools, result = asyncio.run(protocol_exchange(database, handoff))

    assert initialized.server_info.name == "Cloud FinOps Agent"
    assert initialized.protocol_version
    assert {item.name for item in tools.tools} >= {
        "recibir_handoff_arquitectura",
        "ejecutar_analisis_finops",
        "emitir_decision_finops",
    }
    assert result.is_error is False
    assert result.structured_content["duplicate"] is False
    assert result.structured_content["intake"]["operational_status"] == "received"
