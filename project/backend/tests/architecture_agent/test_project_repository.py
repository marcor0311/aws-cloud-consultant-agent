"""Agent 2 repository handoff and local Architecture publication."""

import hashlib
import json
import sqlite3
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from pydantic import ValidationError

from app.architecture.catalog import BaselineCatalog
from app.architecture.demo import DEFAULT_INPUT
from app.architecture.graph import build_graph
from app.architecture.project_repository import (
    ApprovedInput,
    ArchitectureProjectHandoff,
    BoardRecord,
    ProjectRepositoryBridge,
    approved_input_digest,
)
from app.architecture.service import ArchitectureService
from app.integrations.langgraph import LangGraphExecution
from app.persistence.workflow import WorkflowStore

BASELINES = (
    Path(__file__).resolve().parents[5] / "aws-cloud-consultant-baseline-modules"
)
NIKE_PROJECT = (
    Path(__file__).resolve().parents[5]
    / "aws-cloud-consulting-project-nike-01-lindora-run"
)


def git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def git_bytes(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
    ).stdout


def project_repository(root):
    for directory in ProjectRepositoryBridge.REQUIRED_DIRECTORIES:
        (root / directory).mkdir(parents=True, exist_ok=True)
    requirements = root / "docs/01-discovery/requirements.md"
    decision = root / "docs/02-board/decision.md"
    constraints = root / "docs/01-discovery/constraints.md"
    budget = root / "docs/02-board/budget.json"
    requirements.write_text(
        "# Requisitos\n\nAlmacenar documentos privados cifrados.\n",
        encoding="utf-8",
    )
    decision.write_text(
        "# Decisión\n\nProyecto aprobado con presupuesto mensual de USD 75.\n",
        encoding="utf-8",
    )
    constraints.write_text("# Restricciones\n\nRegión us-east-1.\n", encoding="utf-8")
    budget.write_text(
        '{"amount":"75.00","currency":"USD","period":"month"}\n',
        encoding="utf-8",
    )
    git(root, "init")
    git(root, "config", "user.email", "tests@example.invalid")
    git(root, "config", "user.name", "Architecture Tests")
    git(root, "add", ".")
    git(root, "commit", "-m", "Approved Agent 2 inputs")
    commit = git(root, "rev-parse", "HEAD")
    inputs = []
    types = {
        requirements: "requirements",
        constraints: "constraints",
        decision: "decision",
        budget: "budget",
    }
    for path, document_type in types.items():
        relative = path.relative_to(root).as_posix()
        inputs.append(
            {
                "path": relative,
                "document_type": document_type,
                "sha256": hashlib.sha256(
                    git_bytes(root, "show", f"{commit}:{relative}")
                ).hexdigest(),
            }
        )
    return commit, inputs


def handoff(root, commit, inputs):
    validated = [ApprovedInput.model_validate(item) for item in inputs]
    decision = next(item for item in validated if item.document_type == "decision")
    return {
        "contract_version": "1.1",
        "source_stage": 2,
        "case_id": "project-case",
        "project_id": "documentos-demo",
        "repository_path": str(root),
        "repository_url": "https://github.com/example/documentos-demo",
        "source_commit": commit,
        "architecture_issue_url": "https://github.com/example/documentos-demo/issues/3",
        "approved_revision": 1,
        "approved_artifact_sha256": approved_input_digest(1, validated),
        "inputs": deepcopy(inputs),
        "approval": {
            "evidence_type": "test",
            "decision": "approved",
            "document_path": decision.path,
            "document_sha256": decision.sha256,
            "approved_by": "block-c-test-board",
            "approved_at": "2026-11-08T15:00:00-06:00",
        },
    }


def service_at(root):
    root.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(root / "checkpoints.sqlite3", check_same_thread=False)
    store = WorkflowStore(f"sqlite:///{root / 'workflow.sqlite3'}")
    catalog = BaselineCatalog(BASELINES)
    service = ArchitectureService(
        LangGraphExecution(build_graph(SqliteSaver(connection), catalog)),
        catalog,
        store,
    )
    return connection, store, service


def test_reads_pinned_agent_2_inputs_and_publishes_approved_revision(tmp_path):
    repo = tmp_path / "project"
    repo.mkdir()
    commit, inputs = project_repository(repo)
    connection, store, service = service_at(tmp_path / "state")

    context = service.read_project_handoff(handoff(repo, commit, inputs))
    assert context["source_commit"] == commit
    assert {item["path"] for item in context["documents"]} == {
        "docs/01-discovery/requirements.md",
        "docs/01-discovery/constraints.md",
        "docs/02-board/decision.md",
        "docs/02-board/budget.json",
    }

    package = json.loads(DEFAULT_INPUT.read_text(encoding="utf-8"))
    package["source_issue"] = context["architecture_issue_url"]
    package["requirements"][0]["source"] = "docs/01-discovery/requirements.md"
    started = service.start("project-case", commit, package)["state"]
    with pytest.raises(ValueError, match="No existe un handoff"):
        service.get_finops_handoff("project-case", 1)
    service.review("project-case", 1, started["artifact_sha256"], "approve")
    assert service.get_finops_handoff("project-case", 1)["revision"] == 1

    publication = service.publish_to_project("project-case")
    target = Path(publication["path"])
    assert publication["status"] == "published"
    assert (target / "architecture-package.json").is_file()
    assert (target / "pricing-inputs.json").is_file()
    assert (target / "manifest.json").is_file()
    assert service.publish_to_project("project-case")["status"] == "duplicate"
    assert git(repo, "status", "--short")
    store.engine.dispose()
    connection.close()


def test_project_handoff_rejects_unapproved_paths_and_tampered_inputs(tmp_path):
    repo = tmp_path / "project"
    repo.mkdir()
    commit, inputs = project_repository(repo)
    invalid = handoff(repo, commit, inputs)
    invalid["inputs"][0]["path"] = "docs/03-architecture/architecture.md"
    with pytest.raises(ValidationError, match="discovery o board"):
        ArchitectureProjectHandoff.model_validate(invalid)

    tampered = handoff(repo, commit, deepcopy(inputs))
    tampered["inputs"][0]["sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="hash aprobado"):
        ArchitectureProjectHandoff.model_validate(tampered)


def test_project_handoff_requires_all_documents_and_valid_approval(tmp_path):
    repo = tmp_path / "project"
    repo.mkdir()
    commit, inputs = project_repository(repo)
    missing = handoff(repo, commit, inputs)
    missing["inputs"] = [
        item for item in missing["inputs"] if item["document_type"] != "budget"
    ]
    with pytest.raises(ValidationError, match="requiere requirements"):
        ArchitectureProjectHandoff.model_validate(missing)

    invalid_approval = handoff(repo, commit, inputs)
    invalid_approval["approval"]["document_sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="no corresponde"):
        ArchitectureProjectHandoff.model_validate(invalid_approval)

    invalid_manifest = handoff(repo, commit, inputs)
    invalid_manifest["approved_artifact_sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="hash aprobado"):
        ArchitectureProjectHandoff.model_validate(invalid_manifest)


def test_project_context_is_required_to_match_commit_issue_and_sources(tmp_path):
    repo = tmp_path / "project"
    repo.mkdir()
    commit, inputs = project_repository(repo)
    connection, store, service = service_at(tmp_path / "state")
    service.read_project_handoff(handoff(repo, commit, inputs))
    package = json.loads(DEFAULT_INPUT.read_text(encoding="utf-8"))
    package["source_issue"] = "https://github.com/example/documentos-demo/issues/3"
    package["requirements"][0]["source"] = "docs/01-discovery/requirements.md"

    with pytest.raises(ValueError, match="commit aprobado"):
        service.start("project-case", "0" * 40, package)
    wrong_source = deepcopy(package)
    wrong_source["requirements"][0]["source"] = "unapproved.md"
    with pytest.raises(ValueError, match="insumo aprobado"):
        service.start("project-case", commit, wrong_source)
    store.engine.dispose()
    connection.close()


def test_rejects_missing_commit_and_issue_from_another_repository(tmp_path):
    repo = tmp_path / "project"
    repo.mkdir()
    commit, inputs = project_repository(repo)

    missing_commit = handoff(repo, commit, inputs)
    missing_commit["source_commit"] = "0" * 40
    with pytest.raises(ValueError, match="commit aprobado"):
        ProjectRepositoryBridge().read(missing_commit)

    wrong_issue = handoff(repo, commit, inputs)
    wrong_issue["architecture_issue_url"] = (
        "https://github.com/another/project/issues/19"
    )
    with pytest.raises(ValidationError, match="repositorio del proyecto"):
        ArchitectureProjectHandoff.model_validate(wrong_issue)


def test_publication_requires_current_approved_revision(tmp_path):
    repo = tmp_path / "project"
    repo.mkdir()
    commit, inputs = project_repository(repo)
    connection, store, service = service_at(tmp_path / "state")
    context = service.read_project_handoff(handoff(repo, commit, inputs))
    package = json.loads(DEFAULT_INPUT.read_text(encoding="utf-8"))
    package["source_issue"] = context["architecture_issue_url"]
    package["requirements"][0]["source"] = "docs/01-discovery/requirements.md"
    service.start("project-case", commit, package)

    with pytest.raises(ValueError, match="aprobada y lista"):
        service.publish_to_project("project-case")

    store.engine.dispose()
    connection.close()


def test_publication_supports_nested_policies_and_binary_diagram(tmp_path):
    repo = tmp_path / "project"
    repo.mkdir()
    project_repository(repo)
    bridge = ProjectRepositoryBridge()
    documents = {
        "architecture.md": "# Architecture\n",
        "policies/deny.json": '{"Effect":"Deny"}\n',
        "architecture.png": b"\x89PNG\r\n\x1a\nblock-d",
    }

    publication = bridge.publish(str(repo), 1, documents)
    target = Path(publication["path"])
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))

    assert (target / "policies" / "deny.json").is_file()
    assert (target / "architecture.png").read_bytes() == documents["architecture.png"]
    assert {item["path"] for item in manifest["files"]} == set(documents)
    assert bridge.publish(str(repo), 1, documents)["status"] == "duplicate"


def test_service_renders_and_publishes_architecture_1_2(tmp_path):
    repo = tmp_path / "project"
    repo.mkdir()
    commit, inputs = project_repository(repo)
    connection, store, service = service_at(tmp_path / "state")
    context = service.read_project_handoff(handoff(repo, commit, inputs))
    package = json.loads(DEFAULT_INPUT.read_text(encoding="utf-8"))
    package["schema_version"] = "1.2"
    package["source_issue"] = context["architecture_issue_url"]
    package["requirements"][0]["source"] = "docs/01-discovery/requirements.md"
    package["topology"] = {
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
    package["security_controls"] = [
        {
            "control_id": "SEC-001",
            "description": "Deny non-TLS requests.",
            "policy_as_code_path": "policies/deny-insecure.json",
            "iam_policy": {
                "statements": [
                    {
                        "sid": "DenyInsecure",
                        "effect": "Deny",
                        "actions": ["s3:*"],
                        "resources": ["arn:aws:s3:::documents-demo/*"],
                    }
                ]
            },
        }
    ]

    class Renderer:
        def render_bytes(self, source):
            assert "AWS::S3::Bucket" in source
            return b"\x89PNG\r\n\x1a\nblock-d-service"

    service.diagram_renderer = Renderer()
    started = service.start("project-case", commit, package)["state"]
    service.review("project-case", 1, started["artifact_sha256"], "approve")
    publication = service.publish_to_project("project-case")
    target = Path(publication["path"])

    assert (target / "architecture.png").read_bytes().startswith(b"\x89PNG")
    assert (target / "architecture.aws-dac.yaml").is_file()
    assert (target / "resources.yaml").is_file()
    assert (target / "module-selection.yaml").is_file()
    assert (target / "policies" / "deny-insecure.json").is_file()
    assert service.publish_to_project("project-case")["status"] == "duplicate"
    store.engine.dispose()
    connection.close()


@pytest.mark.skipif(not NIKE_PROJECT.is_dir(), reason="Nike Agent 2 repo not present")
def test_reads_real_agent_2_delivery_without_transmitting_pdf_binaries():
    commit = git(NIKE_PROJECT, "rev-parse", "HEAD")
    board_path = (
        "docs/02-board/acta-junta-609a2ec8c4bf4045a0e9a2cd9f98e4e1.json"
    )
    board = json.loads(git_bytes(NIKE_PROJECT, "show", f"{commit}:{board_path}"))
    media_types = {
        ".md": "text/markdown",
        ".html": "text/html",
        ".json": "application/json",
        ".pdf": "application/pdf",
    }
    inputs = []
    for item in board["files"]:
        path = f"docs/01-discovery/{item['name']}"
        inputs.append(
            {
                "document_type": "discovery_evidence",
                "path": path,
                "sha256": item["sha256"],
                "media_type": media_types[Path(path).suffix],
            }
        )
    board_sha256 = hashlib.sha256(
        git_bytes(NIKE_PROJECT, "show", f"{commit}:{board_path}")
    ).hexdigest()
    inputs.append(
        {
            "document_type": "board_record",
            "path": board_path,
            "sha256": board_sha256,
            "media_type": "application/json",
        }
    )
    delivery = {
        "contract_version": "1.2",
        "source_stage": 2,
        "case_id": board["case_id"],
        "project_id": board["case_id"],
        "repository_path": str(NIKE_PROJECT),
        "repository_url": (
            "https://github.com/aws-cloud-consulting-group/"
            "aws-cloud-consulting-project-nike-01-lindora-run"
        ),
        "source_commit": commit,
        "architecture_issue_url": (
            "https://github.com/aws-cloud-consulting-group/"
            "aws-cloud-consulting-project-nike-01-lindora-run/issues/1"
        ),
        "approved_revision": 1,
        "approved_artifact_sha256": board["request_sha256"],
        "inputs": inputs,
        "approval": {
            "evidence_type": "test",
            "decision": "approved",
            "document_path": board_path,
            "document_sha256": board_sha256,
            "approved_by": f"board:{board['id']}",
            "approved_at": board["closed_at"],
            "simulated": True,
            "decision_digest": board["digest"],
            "signature_verification": "declared_by_source",
        },
    }

    context = ProjectRepositoryBridge().read(delivery)

    assert context["contract_version"] == "1.2"
    assert context["board_validation"] == {
        "record_id": board["id"],
        "request_sha256": board["request_sha256"],
        "decision_digest": board["digest"],
        "status": "approved",
        "simulated": True,
        "vote_rule": "unanimity",
        "members": 4,
        "votes": 4,
        "signatures": "declared_by_source",
        "cryptographic_verification_performed": False,
    }
    assert context["budget"]["total"] == "180000"
    pdfs = [
        item for item in context["documents"] if item["media_type"] == "application/pdf"
    ]
    assert pdfs
    assert all(item["content"] is None and item["binary_omitted"] for item in pdfs)
    transcript = next(
        item
        for item in context["documents"]
        if item["path"].endswith("transcripcion-reunion-nike.md")
    )
    assert "Nike Lindora" in transcript["content"]


@pytest.mark.skipif(not NIKE_PROJECT.is_dir(), reason="Nike Agent 2 repo not present")
def test_real_agent_2_delivery_rejects_false_signature_claim():
    commit = git(NIKE_PROJECT, "rev-parse", "HEAD")
    board_path = (
        "docs/02-board/acta-junta-609a2ec8c4bf4045a0e9a2cd9f98e4e1.json"
    )
    raw = git_bytes(NIKE_PROJECT, "show", f"{commit}:{board_path}")
    board = json.loads(raw)
    board["votes"][next(iter(board["votes"]))]["signature_verified"] = False

    with pytest.raises(ValidationError, match="no declara verificadas"):
        BoardRecord.model_validate(board)
