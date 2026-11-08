"""Consumer-driven contract tests for the future FinOps agent boundary."""

import json
from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.architecture.demo import DEFAULT_INPUT, run
from app.architecture.models import ArchitectureFinOpsHandoff


class FinOpsContractConsumer:
    """Minimal consumer: validates the public handoff without pricing anything."""

    @staticmethod
    def read(path):
        return ArchitectureFinOpsHandoff.model_validate_json(path.read_text("utf-8"))


def test_finops_consumer_reads_typed_complete_handoff(tmp_path):
    run(DEFAULT_INPUT, tmp_path)

    handoff = FinOpsContractConsumer.read(tmp_path / "handoff-finops.json")

    assert handoff.contract_version == "1.0"
    assert handoff.economic_contract.contract_version == "1.1"
    assert handoff.handoff_status == "ready"
    assert handoff.economic_contract.budget.currency == "USD"
    assert {item.service_type for item in handoff.economic_contract.pricing_inputs} == {
        "s3",
        "kms",
    }
    s3 = handoff.economic_contract.pricing_inputs[0]
    assert {(item.metric, item.unit) for item in s3.dimensions} >= {
        ("storage", "GB-month"),
        ("requests", "requests/month"),
    }


def test_finops_consumer_detects_explicit_missing_information(tmp_path):
    package = json.loads(DEFAULT_INPUT.read_text(encoding="utf-8"))
    package["economic_contract"]["budget"] = {
        "status": "unknown",
        "amount": None,
        "currency": None,
        "period": None,
        "source": {
            "source_type": "unknown",
            "notes": "El cliente todavía no confirmó el presupuesto.",
        },
    }
    dimension = package["economic_contract"]["pricing_inputs"][0]["dimensions"][0]
    dimension.update(
        quantity=None,
        missing_reason="Falta confirmar el volumen promedio.",
        source={
            "source_type": "unknown",
            "notes": "Pendiente de confirmación del cliente.",
        },
    )
    input_path = tmp_path / "incomplete.json"
    output = tmp_path / "output"
    input_path.write_text(json.dumps(package), encoding="utf-8")

    run(input_path, output)
    handoff = FinOpsContractConsumer.read(output / "handoff-finops.json")

    assert handoff.handoff_status == "blocked"
    assert "budget_unknown" in handoff.blocking_reasons
    assert any(item.startswith("quantity_unknown:documents") for item in handoff.blocking_reasons)


def test_finops_consumer_rejects_invalid_or_tampered_handoff(tmp_path):
    run(DEFAULT_INPUT, tmp_path)
    payload = json.loads((tmp_path / "handoff-finops.json").read_text("utf-8"))

    invalid_service = deepcopy(payload)
    invalid_service["economic_contract"]["pricing_inputs"][0]["service_type"] = "ec2"
    invalid_service["architecture"]["economic_contract"]["pricing_inputs"][0][
        "service_type"
    ] = "ec2"
    with pytest.raises(ValidationError):
        ArchitectureFinOpsHandoff.model_validate(invalid_service)

    tampered = deepcopy(payload)
    tampered["blocking_reasons"] = ["budget_unknown"]
    tampered["handoff_status"] = "blocked"
    with pytest.raises(ValidationError, match="bloqueos deben derivarse"):
        ArchitectureFinOpsHandoff.model_validate(tampered)
