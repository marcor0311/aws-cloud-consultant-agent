"""Cloud Architecture Agent contracts, catalog, review and FinOps handoff."""

import sqlite3
from copy import deepcopy
from pathlib import Path

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from mcp.server.mcpserver.exceptions import ToolError

from app.architecture.catalog import BaselineCatalog
from app.architecture.graph import build_graph
from app.architecture.models import ArchitecturePackage
from app.architecture.service import ArchitectureService
from app.integrations.langgraph import LangGraphExecution
from app.mcp_server import create_server
from app.persistence.workflow import WorkflowStore
from app.workflow.graph import build_process_graph
from app.workflow.service import ProcessService

BASELINES = (
    Path(__file__).resolve().parents[5] / "aws-cloud-consultant-baseline-modules"
)


@pytest.fixture
def proposal():
    return {
        "schema_version": "1.1",
        "project_id": "documentos-demo",
        "source_issue": "https://github.com/example/project/issues/19",
        "region": "us-east-1",
        "environment": "dev",
        "requirements": [
            {
                "requirement_id": "REQ-001",
                "description": "Almacenar documentos privados.",
                "source": "docs/01-discovery/summary.md",
            }
        ],
        "resources": [
            {
                "resource_id": "documents",
                "aws_service": "Amazon S3",
                "purpose": "Almacenamiento cifrado de documentos.",
                "dependencies": [],
                "sizing_assumptions": ["100 GB de almacenamiento promedio"],
            }
        ],
        "baselines": [
            {
                "module_id": "s3",
                "repository": "https://github.com/marcor0311/aws-cloud-consultant-baseline-modules.git",
                "commit": "2450a17830d40439e4eb673d1459140b52d9b93f",
                "candidate_version": "0.1.0",
                "approval_status": "draft",
                "profile": "default",
                "configuration": {
                    "versioning_enabled": True,
                    "kms_key_arn": "required-from-project",
                },
            }
        ],
        "missing_baselines": ["kms"],
        "decisions": [
            {
                "adr_id": "ADR-001",
                "title": "Usar S3 para documentos",
                "decision": "Usar almacenamiento de objetos privado y cifrado.",
                "alternatives": ["EFS"],
                "tradeoffs": ["S3 no ofrece semántica de filesystem POSIX."],
            }
        ],
        "security_controls": [
            {
                "control_id": "SEC-001",
                "description": "Bloquear acceso público y exigir TLS.",
                "policy_as_code_path": "docs/03-architecture/policies/s3.rego",
            }
        ],
        "cost_assumptions": [
            {
                "resource_id": "documents",
                "metric": "almacenamiento promedio",
                "quantity": 100,
                "unit": "GB-month",
            }
        ],
        "economic_contract": {
            "contract_version": "1.1",
            "budget": {
                "status": "known",
                "amount": "75.00",
                "currency": "USD",
                "period": "month",
                "source": {
                    "source_type": "client",
                    "source_reference": "https://github.com/example/project/issues/19",
                },
            },
            "pricing_inputs": [
                {
                    "service_type": "s3",
                    "resource_id": "documents",
                    "aws_service": "Amazon S3",
                    "service_code": "AmazonS3",
                    "region": "us-east-1",
                    "dimensions": [
                        {
                            "dimension_id": "standard-storage",
                            "metric": "storage",
                            "quantity": "100",
                            "unit": "GB-month",
                            "source": {
                                "source_type": "requirement",
                                "source_reference": "REQ-001",
                            },
                            "requirement_ids": ["REQ-001"],
                            "storage_class": "STANDARD",
                        }
                    ],
                }
            ],
        },
        "diagram_mermaid": "flowchart LR\n  client --> documents[S3]",
        "risks": ["El costo depende del patrón de solicitudes."],
        "open_questions": ["Confirmar retención."],
    }


def service_at(path):
    connection = sqlite3.connect(path, check_same_thread=False)
    catalog = BaselineCatalog(BASELINES)
    service = ArchitectureService(
        LangGraphExecution(build_graph(SqliteSaver(connection), catalog)), catalog
    )
    return connection, service


def test_catalog_reads_real_modules_and_pending_approval():
    modules = BaselineCatalog(BASELINES).modules()
    assert {module["module_id"] for module in modules} == {
        "s3",
        "dynamodb",
        "api-gateway",
    }
    assert all(module["production_approval"] == "pending" for module in modules)


def test_contract_rejects_unknown_dependencies_and_false_baseline_status(proposal):
    invalid = deepcopy(proposal)
    invalid["resources"][0]["dependencies"] = ["unknown"]
    with pytest.raises(ValueError, match="dependencias"):
        ArchitecturePackage.model_validate(invalid)

    package = ArchitecturePackage.model_validate(proposal)
    package.baselines[0].approval_status = "approved"
    with pytest.raises(ValueError, match="no coincide"):
        BaselineCatalog(BASELINES).validate(package.baselines)

    package = ArchitecturePackage.model_validate(proposal)
    package.baselines[0].commit = "0" * 40
    with pytest.raises(ValueError, match="commit baseline"):
        BaselineCatalog(BASELINES).validate(package.baselines)


def test_contract_rejects_circular_deployment_dependencies(proposal):
    invalid = deepcopy(proposal)
    invalid["resources"][0]["dependencies"] = ["documents-key"]
    invalid["resources"].append(
        {
            "resource_id": "documents-key",
            "aws_service": "AWS KMS",
            "purpose": "Encrypt documents.",
            "dependencies": ["documents"],
            "sizing_assumptions": ["One key"],
        }
    )
    with pytest.raises(ValueError, match="cíclicas"):
        ArchitecturePackage.model_validate(invalid)


def test_legacy_1_0_contract_remains_parseable_but_blocks_finops(proposal):
    legacy = deepcopy(proposal)
    legacy["schema_version"] = "1.0"
    del legacy["economic_contract"]

    package = ArchitecturePackage.model_validate(legacy)

    assert package.cost_assumptions[0].quantity == 100
    assert package.finops_blocking_reasons() == ["economic_contract_missing"]


def test_legacy_economic_1_0_is_readable_but_requires_explicit_upgrade(proposal):
    legacy = deepcopy(proposal)
    contract = legacy["economic_contract"]
    contract["contract_version"] = "1.0"
    pricing_input = contract["pricing_inputs"][0]
    pricing_input.pop("service_type")
    dimension = pricing_input["dimensions"][0]
    dimension["pricing_attributes"] = {
        "storage_class": dimension.pop("storage_class")
    }

    package = ArchitecturePackage.model_validate(legacy)

    assert package.economic_contract.contract_version == "1.0"
    assert package.finops_blocking_reasons() == [
        "economic_contract_upgrade_required"
    ]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (
            lambda payload: payload["economic_contract"]["pricing_inputs"][0].update(
                region="eu-west-1"
            ),
            "región económica",
        ),
        (
            lambda payload: payload["economic_contract"]["pricing_inputs"][0][
                "dimensions"
            ][0].update(quantity="-1"),
            "greater than or equal to 0",
        ),
        (
            lambda payload: payload["economic_contract"]["pricing_inputs"][0][
                "dimensions"
            ][0].update(requirement_ids=["REQ-999"]),
            "requisitos desconocidos",
        ),
        (
            lambda payload: payload["economic_contract"]["pricing_inputs"][0][
                "dimensions"
            ][0].update(unit="banana"),
            "Input should be",
        ),
        (
            lambda payload: payload["economic_contract"]["pricing_inputs"][0][
                "dimensions"
            ][0].update(metric="api_requests", unit="GB-month"),
            "Input should be",
        ),
        (
            lambda payload: payload["economic_contract"]["pricing_inputs"][0][
                "dimensions"
            ][0].update(
                source={
                    "source_type": "requirement",
                    "source_reference": "REQ-999",
                }
            ),
            "procedencia requirement",
        ),
    ],
)
def test_economic_contract_rejects_invalid_inputs(proposal, change, message):
    invalid = deepcopy(proposal)
    change(invalid)
    with pytest.raises(ValueError, match=message):
        ArchitecturePackage.model_validate(invalid)


def test_unknown_values_are_explicit_and_block_handoff(proposal, tmp_path):
    incomplete = deepcopy(proposal)
    incomplete["economic_contract"]["budget"] = {
        "status": "unknown",
        "amount": None,
        "currency": None,
        "period": None,
        "source": {
            "source_type": "unknown",
            "notes": "El cliente todavía no informó un presupuesto.",
        },
    }
    dimension = incomplete["economic_contract"]["pricing_inputs"][0]["dimensions"][0]
    dimension.update(
        quantity=None,
        missing_reason="Falta confirmar el almacenamiento promedio.",
        source={
            "source_type": "unknown",
            "notes": "Pendiente de confirmación del cliente.",
        },
    )
    connection, service = service_at(tmp_path / "blocked.sqlite3")
    current = service.start("blocked", "issue-19", incomplete)["state"]
    final = service.review(
        "blocked", 1, current["artifact_sha256"], "approve"
    )["state"]

    assert final["status"] == "blocked_for_finops_inputs"
    assert final["handoff"]["handoff_status"] == "blocked"
    assert "budget_unknown" in final["handoff"]["blocking_reasons"]
    assert any(
        reason.startswith("quantity_unknown:documents")
        for reason in final["handoff"]["blocking_reasons"]
    )
    connection.close()


def test_complete_examples_validate_and_generate_pricing_artifact():
    examples = Path(__file__).resolve().parents[2] / "examples"
    for filename in ("architecture-1.json", "architecture-serverless.json"):
        package = ArchitecturePackage.model_validate_json(
            (examples / filename).read_text(encoding="utf-8")
        )
        BaselineCatalog(BASELINES).validate(package.baselines)
        assert package.finops_blocking_reasons() == []
        assert "pricing-inputs.json" in package.artifacts()


def test_review_requires_exact_revision_and_persists_restart(tmp_path, proposal):
    path = tmp_path / "architecture.sqlite3"
    connection, service = service_at(path)
    started = service.start("case-19", "issue-19-v1", proposal)
    state = started["state"]
    assert state["status"] == "awaiting_review"
    assert started["pending"][0]["action"] == "architect_review"
    assert "main.tf" not in state["documents"]
    with pytest.raises(ValueError, match="revisión pendiente exacta"):
        service.review("case-19", 1, "0" * 64, "approve")
    service.review(
        "case-19", 1, state["artifact_sha256"], "revise", "Aclarar retención."
    )
    corrected = deepcopy(proposal)
    corrected["open_questions"] = []
    reviewed = service.replace("case-19", 1, corrected)
    assert reviewed["state"]["revision"] == 2
    digest = reviewed["state"]["artifact_sha256"]
    final = service.review("case-19", 2, digest, "approve")
    assert final["state"]["status"] == "ready_for_finops"
    assert final["state"]["handoff"]["target_stage"] == 4
    assert final["state"]["handoff"]["contract_version"] == "1.0"
    assert final["state"]["handoff"]["architecture_schema_version"] == "1.1"
    assert final["state"]["handoff"]["source_issue"] == proposal["source_issue"]
    exported = service.get_finops_handoff("case-19", 2)
    assert exported == final["state"]["handoff"]
    with pytest.raises(ValueError, match="No existe un handoff"):
        service.get_finops_handoff("case-19", 99)
    connection.close()

    connection, restarted = service_at(path)
    assert restarted.get("case-19")["state"]["handoff"] == final["state"]["handoff"]
    connection.close()


def test_mcp_exposes_architecture_without_terraform_generation(tmp_path, proposal):
    connection, service = service_at(tmp_path / "mcp.sqlite3")

    class Runtime:
        architecture = service

    server = create_server(None, Runtime())

    tools = server._tool_manager._tools
    assert {
        "consultar_catalogo_baselines",
        "iniciar_arquitectura",
        "consultar_arquitectura",
        "corregir_arquitectura",
        "revisar_arquitectura",
    } <= set(tools)
    result = tools["iniciar_arquitectura"].fn("case", "issue-19", proposal)
    state = result["state"]
    with pytest.raises(ToolError, match="revisión pendiente exacta"):
        tools["revisar_arquitectura"].fn("case", 1, "0" * 64, "approve", "")
    assert all(not name.endswith(".tf") for name in state["documents"])
    connection.close()


def test_approved_architecture_advances_main_process_to_finops(tmp_path, proposal):
    connection = sqlite3.connect(
        tmp_path / "checkpoints.sqlite3", check_same_thread=False
    )
    saver = SqliteSaver(connection)
    store = WorkflowStore(f"sqlite:///{tmp_path / 'workflow.sqlite3'}")
    store.put("owner:case", "owner", {"case_id": "case", "manager_id": "manager"})
    process = ProcessService(
        LangGraphExecution(build_process_graph(saver)), store, "manager"
    )
    process.ensure("case")
    digest = "a" * 64
    process.internal("case", "transcript:1", "transcript.available")
    process.internal(
        "case",
        "preparation.ready:1",
        "preparation.ready",
        revision=1,
        artifact_sha256=digest,
        evidence=["artifact:case:1"],
    )
    process.internal(
        "case",
        "preparation.approved:1",
        "preparation.approved",
        revision=1,
        artifact_sha256=digest,
        evidence=["artifact:case:1"],
    )
    process.internal(
        "case",
        "direction.approved:1",
        "stage.approved",
        revision=1,
        artifact_sha256=digest,
        evidence=["artifact:case:1"],
    )
    catalog = BaselineCatalog(BASELINES)
    service = ArchitectureService(
        LangGraphExecution(build_graph(saver, catalog)),
        catalog,
        store,
        process,
        "cloud-solutions-architect",
    )
    current = service.start("case", "issue-19", proposal)["state"]
    service.review("case", 1, current["artifact_sha256"], "approve")
    assert process.get("case")["state"]["stage"] == 4
    assert process.get("case")["state"]["status"] == "awaiting_deliverable"
    handoff = store.handoff("case:stage-3:stage-4:v1")
    assert handoff["to_actor"] == "finops-agent"
    store.engine.dispose()
    connection.close()
