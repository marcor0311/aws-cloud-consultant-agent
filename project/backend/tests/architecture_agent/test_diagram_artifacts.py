"""Typed topology, deterministic artifacts and pinned awsdac adapter."""

import json
import os
import re
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from app.architecture.diagram_renderer import AwsDacRenderer
from app.architecture.models import ArchitecturePackage
from app.architecture.topology import AWSDAC_DEFINITION_URL, AWSDAC_VERSION

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "architecture-1.json"
DEPENDENCIES = (
    Path(__file__).resolve().parents[2] / "tools" / "awsdac" / "dependencies.json"
)


@pytest.fixture
def proposal():
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def test_awsdac_dependency_manifest_pins_supported_platforms_and_hashes():
    manifest = json.loads(DEPENDENCIES.read_text(encoding="utf-8"))
    assert manifest["version"] == AWSDAC_VERSION
    assert set(manifest["assets"]) == {
        "darwin-amd64",
        "darwin-arm64",
        "linux-386",
        "linux-amd64",
        "linux-arm",
        "linux-arm64",
        "windows-386",
        "windows-amd64",
    }
    for platform, asset in manifest["assets"].items():
        assert asset["filename"] == f"awsdac-v{AWSDAC_VERSION}_{platform}.zip"
        assert re.fullmatch(r"[0-9a-f]{64}", asset["sha256"])


def architecture_1_2(proposal):
    payload = deepcopy(proposal)
    payload["schema_version"] = "1.2"
    payload["topology"] = {
        "nodes": [
            {
                "resource_id": "documents",
                "aws_resource_type": "AWS::S3::Bucket",
                "title": "Private documents",
            },
            {
                "resource_id": "documents-key",
                "aws_resource_type": "AWS::KMS",
                "title": "Documents encryption key",
            },
        ],
        "relations": [
            {
                "relation_id": "REL-001",
                "source": "documents-key",
                "target": "documents",
                "relation_type": "deployment_dependency",
                "label": "encrypts",
            }
        ],
    }
    payload["security_controls"] = [
        {
            "control_id": "SEC-001",
            "description": "Deny non-TLS access to the documents bucket.",
            "policy_as_code_path": "policies/deny-insecure-transport.json",
            "iam_policy": {
                "statements": [
                    {
                        "sid": "DenyInsecureTransport",
                        "effect": "Deny",
                        "actions": ["s3:*"],
                        "resources": [
                            "arn:aws:s3:::documents-demo",
                            "arn:aws:s3:::documents-demo/*",
                        ],
                    }
                ]
            },
        }
    ]
    return payload


def test_topology_generates_mermaid_awsdac_manifests_and_policy(proposal):
    package = ArchitecturePackage.model_validate(architecture_1_2(proposal))
    artifacts = package.artifacts()

    assert package.diagram_mermaid == (
        'flowchart LR\n  documents["Private documents"]\n'
        '  documents_key["Documents encryption key"]\n'
        '  documents_key -.->|"encrypts"| documents\n'
    )
    diagram = yaml.safe_load(artifacts["architecture.aws-dac.yaml"])["Diagram"]
    assert diagram["DefinitionFiles"][0]["Url"] == AWSDAC_DEFINITION_URL
    assert set(diagram["Resources"]) == {
        "Canvas",
        "documents",
        "documents-key",
    }
    assert diagram["Links"][0]["LineStyle"] == "dashed"
    resources = yaml.safe_load(artifacts["resources.yaml"])["resources"]
    assert resources[0] == {
        "resource_id": "documents",
        "aws_service": "Amazon S3",
        "aws_resource_type": "AWS::S3::Bucket",
        "dependencies": ["documents-key"],
    }
    assert (
        yaml.safe_load(artifacts["module-selection.yaml"])["modules"][0]["commit"]
        == "2450a17830d40439e4eb673d1459140b52d9b93f"
    )
    policy = json.loads(artifacts["policies/deny-insecure-transport.json"])
    assert policy["Version"] == "2012-10-17"
    assert policy["Statement"][0]["Effect"] == "Deny"


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda payload: payload["topology"]["nodes"].append(
                {
                    "resource_id": "unknown",
                    "aws_resource_type": "AWS::SQS::Queue",
                    "title": "Not in architecture resources",
                }
            ),
            "exactamente los recursos",
        ),
        (
            lambda payload: payload["topology"]["relations"].append(
                {
                    "relation_id": "REL-999",
                    "source": "documents",
                    "target": "unknown",
                    "relation_type": "functional",
                    "label": "invalid",
                }
            ),
            "nodos existentes",
        ),
        (
            lambda payload: payload["security_controls"][0].update(
                policy_as_code_path="../escape.json"
            ),
            "policies/",
        ),
        (
            lambda payload: payload["topology"]["nodes"][0].update(
                aws_resource_type="AWS::Invented::Service"
            ),
            "Tipo AWS no verificado",
        ),
    ],
)
def test_architecture_1_2_rejects_inconsistent_artifacts(proposal, mutate, message):
    payload = architecture_1_2(proposal)
    mutate(payload)
    with pytest.raises(ValueError, match=message):
        ArchitecturePackage.model_validate(payload)


def test_awsdac_renderer_requires_pinned_version_and_nonempty_png(
    tmp_path, monkeypatch
):
    executable = tmp_path / "awsdac.exe"
    executable.write_bytes(b"placeholder")
    source = tmp_path / "diagram.yaml"
    source.write_text("Diagram: {}\n", encoding="utf-8")
    output = tmp_path / "diagram.png"

    monkeypatch.setattr("shutil.which", lambda _: str(executable))

    def run(command, **kwargs):
        if "--version" in command:
            return subprocess.CompletedProcess(
                command, 0, f"awsdac v{AWSDAC_VERSION}\n", ""
            )
        output.write_bytes(b"\x89PNG\r\n\x1a\nblock-d")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("subprocess.run", run)
    assert AwsDacRenderer().render(source, output) == output
    assert output.read_bytes().startswith(b"\x89PNG")


def test_awsdac_renderer_rejects_another_version(tmp_path, monkeypatch):
    executable = tmp_path / "awsdac.exe"
    executable.write_bytes(b"placeholder")
    monkeypatch.setattr("shutil.which", lambda _: str(executable))
    monkeypatch.setattr(
        "subprocess.run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command, 0, "awsdac v0.23\n", ""
        ),
    )
    with pytest.raises(RuntimeError, match="se requiere 0.24"):
        AwsDacRenderer().verify_version()


@pytest.mark.skipif(
    not os.getenv("AWSDAC_EXECUTABLE"),
    reason="real pinned awsdac executable not configured",
)
def test_real_pinned_awsdac_renders_generated_architecture(proposal):
    package = ArchitecturePackage.model_validate(architecture_1_2(proposal))
    source = package.artifacts()["architecture.aws-dac.yaml"]
    image = AwsDacRenderer().render_bytes(source)
    assert image.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(image) > 1024
