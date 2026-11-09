"""Focused integration journey for the FinOps intake boundary."""

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.architecture.demo import DEFAULT_INPUT
from app.architecture.economics import S3PricingInput
from app.architecture.metrics import FinOpsHandoffAcceptance
from app.architecture.models import ArchitectureFinOpsHandoff, ArchitecturePackage
from app.architecture.service import ArchitectureService
from app.finops.analysis import BudgetReference, FinOpsEconomicAnalyzer
from app.finops.calculator import PricingCalculatorPreparer
from app.finops.evidence import S3ExportEvidenceBuilder
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


def test_real_s3_export_matches_the_prepared_calculator_input():
    payload = handoff_payload()
    intake = FinOpsIntake(
        case_id="block-c-s3",
        project_id=payload["architecture"]["project_id"],
        handoff=payload,
        acceptance=FinOpsHandoffAcceptance(
            case_id="block-c-s3",
            revision=1,
            artifact_sha256=payload["artifact_sha256"],
            accepted_by="finops-agent",
            accepted_at="2026-11-09T00:50:02-06:00",
            finops_reference="finops://block-c-s3/intakes/1",
        ),
    )
    preparation = PricingCalculatorPreparer().prepare(intake)
    export_path = (
        Path(__file__).resolve().parents[4]
        / "docs/evidence/agent4/block-c-s3/aws-pricing-calculator-export.json"
    )
    raw = export_path.read_bytes()

    evidence = S3ExportEvidenceBuilder().build(
        preparation,
        "documents",
        json.loads(raw),
        {
            "artifact_type": "export_json",
            "path": "docs/evidence/agent4/block-c-s3/"
            "aws-pricing-calculator-export.json",
            "media_type": "application/json",
            "sha256": hashlib.sha256(raw).hexdigest(),
        },
        datetime(2026, 11, 9, 0, 50, 2, tzinfo=timezone(timedelta(hours=-6))),
    )

    assert evidence.status == "verified"
    assert evidence.monthly_cost == Decimal("3.24")
    assert evidence.currency == "USD"
    assert evidence.region == "us-east-1"
    assert evidence.estimate_url.endswith("bad2a0531379cb5d5aec0c4b36c820b57532c8bd")
    assert {item.dimension_id for item in evidence.parameters} == {
        "standard-storage",
        "get-requests",
        "internet-transfer",
    }

    changed_ui = deepcopy(json.loads(raw))
    changed_ui["Groups"]["Services"][0]["Properties"][
        "S3 Standard storage"
    ] = "100 TB per month"
    partial = S3ExportEvidenceBuilder().build(
        preparation,
        "documents",
        changed_ui,
        evidence.artifacts[0],
        evidence.executed_at,
    )
    assert partial.status == "partial"
    assert partial.unrepresentable_parameters[0].startswith(
        "ui_mismatch:standard-storage:"
    )


def test_economic_analysis_reports_verified_subtotal_and_incomplete_coverage():
    payload = handoff_payload()
    intake = FinOpsIntake(
        case_id="block-c-s3",
        project_id=payload["architecture"]["project_id"],
        handoff=payload,
        acceptance=FinOpsHandoffAcceptance(
            case_id="block-c-s3",
            revision=1,
            artifact_sha256=payload["artifact_sha256"],
            accepted_by="finops-agent",
            accepted_at="2026-11-09T00:50:02-06:00",
            finops_reference="finops://block-c-s3/intakes/1",
        ),
    )
    evidence_path = (
        Path(__file__).resolve().parents[4]
        / "docs/evidence/agent4/block-c-s3/pricing-calculator-evidence.json"
    )
    evidence = json.loads(evidence_path.read_text("utf-8"))

    analysis = FinOpsEconomicAnalyzer().analyze(intake, [evidence])

    assert analysis.operational_status == "partial"
    assert analysis.budget_result == "not_evaluable"
    assert analysis.verified_monthly_subtotal == Decimal("3.24")
    assert analysis.verified_annual_subtotal == Decimal("38.88")
    assert analysis.breakdown[0].share_of_verified_subtotal_percent == 100
    assert analysis.coverage.resource_coverage_percent == 50
    assert analysis.coverage.dimension_coverage_percent == 60
    assert analysis.coverage.pending_resources == ["documents-key"]
    assert analysis.coverage.excluded_costs == ["documents-key: AWS KMS"]
    comparison = analysis.budget_comparison
    assert comparison.status == "coverage_incomplete"
    assert comparison.monthly_budget == Decimal("75.00")
    assert comparison.annual_budget == Decimal("900.00")
    assert comparison.monthly_variance == Decimal("71.76")
    assert comparison.annual_variance == Decimal("861.12")
    assert comparison.absolute_difference == Decimal("71.76")
    assert comparison.difference_percent == Decimal("95.68")
    assert comparison.verified_subtotal_percent_of_budget == Decimal("4.32")
    assert analysis.scenarios[0].status == "partial"
    assert all(item.status == "blocked" for item in analysis.scenarios[1:])
    assert analysis.decision_reference is None

    mismatched = deepcopy(evidence)
    mismatched["architecture_revision"] = 2
    with pytest.raises(ValueError, match="no corresponde al handoff"):
        FinOpsEconomicAnalyzer().analyze(intake, [mismatched])


def test_currency_mismatch_blocks_budget_comparison_without_conversion():
    comparison = FinOpsEconomicAnalyzer.compare_budget(
        Decimal("3.24"),
        "USD",
        BudgetReference(
            status="known",
            amount="50000",
            currency="CRC",
            period="month",
            source_reference="approved://agent-2/budget",
            approval_reference="approved://agent-2/decision",
        ),
        coverage_complete=True,
    )

    assert comparison.status == "currency_mismatch"
    assert comparison.monthly_variance is None
    assert comparison.absolute_difference is None
    assert comparison.difference_percent is None
    assert comparison.blocking_reasons == [
        "currency_mismatch:USD:CRC",
        "authorized_dated_exchange_rate_required",
    ]
