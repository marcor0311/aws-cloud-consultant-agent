"""Focused integration journey for the FinOps intake boundary."""

from copy import deepcopy
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.architecture.demo import DEFAULT_INPUT
from app.architecture.economics import S3PricingInput
from app.architecture.metrics import FinOpsHandoffAcceptance
from app.architecture.models import ArchitectureFinOpsHandoff, ArchitecturePackage
from app.architecture.service import ArchitectureService
from app.finops.calculator import PricingCalculatorPreparer
from app.finops.models import FinOpsEvaluationDecision, FinOpsIntake
from app.finops.service import FinOpsIntakeService
from app.persistence.workflow import WorkflowStore


def handoff_payload():
    package = ArchitecturePackage.model_validate_json(DEFAULT_INPUT.read_text("utf-8"))
    sha256 = ArchitectureService.digest(package.model_dump(mode="json"))
    return ArchitectureFinOpsHandoff(
        handoff_status="ready",
        revision=1,
        artifact_sha256=sha256,
        source_issue=package.source_issue,
        architecture_schema_version=package.schema_version,
        architecture=package,
        economic_contract=package.economic_contract,
        documents=sorted(package.artifacts()),
    ).model_dump(mode="json")


def persisted_service(tmp_path, payload):
    database = f"sqlite:///{tmp_path / 'workflow.sqlite3'}"
    store = WorkflowStore(database, clock=lambda: 1_800_000_000.0)
    store.create_handoff(
        "case-finops:stage-3:stage-4:v1",
        "case-finops",
        "architect",
        "finops-agent",
        "stage-3",
        "stage-4",
        revision=1,
        artifact_sha256=payload["artifact_sha256"],
    )
    return database, store, FinOpsIntakeService(store)


def test_finops_receives_exact_handoff_idempotently_and_recovers(tmp_path):
    payload = handoff_payload()
    database, store, service = persisted_service(tmp_path, payload)

    first = service.receive("case-finops", payload)
    second = service.receive("case-finops", payload)

    assert first["duplicate"] is False
    assert second["duplicate"] is True
    assert first["intake"]["acceptance"]["contract_version"] == "1.0"
    assert first["intake"]["operational_status"] == "received"
    store.engine.dispose()

    restarted_store = WorkflowStore(database)
    recovered = FinOpsIntakeService(restarted_store).get("case-finops", 1)
    assert recovered == first["intake"]
    assert len(restarted_store.list("finops_intake")) == 1
    restarted_store.engine.dispose()


def test_finops_rejects_blocked_tampered_or_unpersisted_handoff(tmp_path):
    payload = handoff_payload()
    _, store, service = persisted_service(tmp_path, payload)

    blocked = deepcopy(payload)
    blocked["architecture"]["economic_contract"]["budget"] = {
        "status": "unknown",
        "amount": None,
        "currency": None,
        "period": None,
        "source": {"source_type": "unknown", "notes": "Falta presupuesto."},
    }
    blocked["economic_contract"] = deepcopy(
        blocked["architecture"]["economic_contract"]
    )
    blocked["handoff_status"] = "blocked"
    blocked["blocking_reasons"] = ["budget_unknown", "budget_source_unknown"]
    with pytest.raises(ValueError, match="handoff bloqueado"):
        service.receive("case-finops", blocked)

    tampered = deepcopy(payload)
    tampered["architecture"]["risks"].append("Contenido alterado en tránsito.")
    with pytest.raises(ValueError, match="SHA-256"):
        service.receive("case-finops", tampered)

    with pytest.raises(ValueError, match="no existe en persistencia"):
        service.receive("another-case", payload)
    store.engine.dispose()


def test_budget_result_does_not_authorize_evaluation():
    base = {
        "decision_id": "decision:case-finops:1",
        "case_id": "case-finops",
        "project_id": "project-finops",
        "architecture_revision": 1,
        "architecture_sha256": "a" * 64,
        "evaluation_reference": "finops://case-finops/evaluations/1",
        "budget_result": "within_budget",
        "decision": "approved",
        "rationale": "La estimación está dentro del presupuesto.",
        "decided_by": "finops-analyst",
        "decided_at": datetime.now(timezone.utc),
    }
    with pytest.raises(ValidationError, match="autorización trazable"):
        FinOpsEvaluationDecision.model_validate(base)

    approved = FinOpsEvaluationDecision.model_validate(
        {**base, "authorization_reference": "github://reviews/123"}
    )
    assert approved.budget_result == "within_budget"
    assert approved.decision == "approved"


def test_calculator_preparation_preserves_s3_values_and_traceability():
    payload = handoff_payload()
    intake = FinOpsIntake(
        case_id="case-finops",
        project_id=payload["architecture"]["project_id"],
        handoff=payload,
        acceptance=FinOpsHandoffAcceptance(
            case_id="case-finops",
            revision=1,
            artifact_sha256=payload["artifact_sha256"],
            accepted_by="finops-agent",
            accepted_at=datetime.now(timezone.utc),
            finops_reference="finops://case-finops/intakes/1",
        ),
    )

    prepared = PricingCalculatorPreparer().prepare(intake)

    assert prepared.status == "partial"
    assert prepared.architecture_sha256 == payload["artifact_sha256"]
    s3 = next(item for item in prepared.resources if item.service_type == "s3")
    assert s3.status == "ready"
    assert [item.dimension_id for item in s3.dimensions] == [
        "standard-storage",
        "get-requests",
        "internet-transfer",
    ]
    storage = s3.dimensions[0]
    assert storage.calculator_parameter == "monthly_storage"
    assert storage.quantity == 100
    assert storage.unit == "GB-month"
    assert storage.attributes == {"storage_class": "STANDARD"}
    assert storage.source.source_reference == "REQ-001"
    assert storage.requirement_ids == ["REQ-001"]
    kms = next(item for item in prepared.resources if item.service_type == "kms")
    assert kms.status == "blocked"
    assert kms.dimensions[1].attributes == {"operation_group": "symmetric"}
    assert all(
        item.blocking_reason.startswith("unsupported_dimension:kms:")
        for item in kms.dimensions
    )


def test_s3_missing_quantity_is_blocked_without_default_value():
    package = ArchitecturePackage.model_validate_json(DEFAULT_INPUT.read_text("utf-8"))
    s3_payload = package.economic_contract.pricing_inputs[0].model_dump(mode="json")
    dimension = s3_payload["dimensions"][0]
    dimension["quantity"] = None
    dimension["missing_reason"] = "El cliente debe confirmar el volumen mensual."
    dimension["source"] = {
        "source_type": "unknown",
        "notes": "No existe evidencia de la cantidad.",
    }
    s3 = S3PricingInput.model_validate(s3_payload)

    prepared = PricingCalculatorPreparer().prepare_resource(s3)

    missing = prepared.dimensions[0]
    assert prepared.status == "blocked"
    assert missing.quantity is None
    assert missing.calculator_parameter == "monthly_storage"
    assert missing.blocking_reason.startswith("missing_quantity:standard-storage:")
