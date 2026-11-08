"""Visible architecture demo exports reviewable artifacts without Terraform."""

import json
from pathlib import Path

from app.architecture.demo import DEFAULT_INPUT, run


def test_demo_exports_architecture_and_finops_handoff(tmp_path):
    result = run(DEFAULT_INPUT, tmp_path)
    assert result["status"] == "ready_for_finops"
    assert result["terraform_generated"] is False
    assert result["aws_credentials_used"] is False
    assert (tmp_path / "architecture.mmd").is_file()
    assert (tmp_path / "architecture-package.json").is_file()
    assert (tmp_path / "pricing-inputs.json").is_file()
    handoff = json.loads((tmp_path / "handoff-finops.json").read_text("utf-8"))
    assert handoff["target_stage"] == 4
    assert handoff["handoff_status"] == "ready"
    assert handoff["contract_version"] == "1.0"
    assert handoff["architecture_schema_version"] == "1.1"
    assert handoff["architecture"]["region"] == "us-east-1"
    assert handoff["economic_contract"]["pricing_inputs"][0]["service_code"] == "AmazonS3"
    assert not list(Path(tmp_path).glob("*.tf"))
