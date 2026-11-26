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
from app.core.architecture_delivery import ArchitectureProjectDelivery
from app.finops.service import FinOpsService
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
        path = root / directory
        path.mkdir(parents=True, exist_ok=True)
        (path / ".gitkeep").touch()
    requirements = root / "docs/01-discovery/requirements.md"
    decision = root / "docs/02-board/decision.md"
    constraints = root / "docs/01-discovery/constraints.md"
    html_summary = root / "docs/01-discovery/summary.html"
    metadata = root / "docs/01-discovery/metadata.json"
    evidence_pdf = root / "docs/01-discovery/evidence.pdf"
    notes = root / "docs/01-discovery/notes.md"
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
    html_summary.write_text("<h1>Resumen aprobado</h1>\n", encoding="utf-8")
    metadata.write_text('{"approved": true}\n', encoding="utf-8")
    evidence_pdf.write_bytes(b"%PDF-1.4\n% approved test evidence\n")
    notes.write_text("# Notas\n\nEvidencia complementaria.\n", encoding="utf-8")
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


def handoff_v13(root, commit, discovery_count=3):
    repository_url = "https://github.com/example/agent2-project"
    document_path = "docs/01-discovery/requirements.md"
    evidence_paths = [
        (document_path, "text/markdown"),
        ("docs/01-discovery/summary.html", "text/html"),
        ("docs/01-discovery/evidence.pdf", "application/pdf"),
        ("docs/01-discovery/metadata.json", "application/json"),
        ("docs/01-discovery/constraints.md", "text/markdown"),
        ("docs/01-discovery/notes.md", "text/markdown"),
    ][:discovery_count]
    request_sha256 = "1" * 64
    decision_digest = "2" * 64
    body = (
        "# Encargo de Arquitectura\n\n"
        "Contexto aprobado.\n\n"
        "USD 75.00\n\n- AWS: USD 75.00\n\n"
        "Diseñar almacenamiento privado.\n\n"
        "Usar us-east-1.\n\n"
        "Arquitectura y ADR.\n\n"
        "Revisión explícita del arquitecto.\n\n"
        f"[{document_path}]({repository_url}/blob/{commit}/{document_path})\n\n"
        f"<!-- meeting-assistant:project-case:{request_sha256} -->"
    )
    delivery = {
        "contract_version": "1.3",
        "source_stage": 2,
        "case_id": "project-case",
        "project_id": "agent2-project",
        "request_sha256": request_sha256,
        "architect": "cloud-architect",
        "repository": {
            "url": repository_url,
            "full_name": "example/agent2-project",
            "default_branch": "main",
            "id": 10,
        },
        "published_commit": {
            "sha": commit,
            "url": f"{repository_url}/commit/{commit}",
        },
        "initial_pull_request": {
            "number": 1,
            "url": f"{repository_url}/pull/1",
            "merged": True,
            "merge_sha": commit,
        },
        "architecture_issue": {
            "number": 2,
            "url": f"{repository_url}/issues/2",
            "title": "[Arquitectura] AWS Cloud Consulting Project Demo",
            "assignee": "cloud-architect",
            "assignment_pending": False,
            "template_sha256": "3" * 64,
            "body_sha256": hashlib.sha256(body.encode()).hexdigest(),
        },
        "approved_package": {
            "revision": 5,
            "artifact_sha256": "4" * 64,
            "files_sha256": "5" * 64,
        },
        "inputs": [
            {
                "path": path,
                "sha256": hashlib.sha256(
                    git_bytes(root, "show", f"{commit}:{path}")
                ).hexdigest(),
                "media_type": media_type,
            }
            for path, media_type in evidence_paths
        ],
        "budget": {
            "currency": "USD",
            "total": "75.00",
            "accepted": True,
            "lines": [{"name": "AWS", "amount": "75.00"}],
            "conditions": "Límite aprobado por Dirección.",
        },
        "work": {
            "context": "Contexto aprobado.",
            "scope": "Diseñar almacenamiento privado.",
            "restrictions": "Usar us-east-1.",
            "deliverables": "Arquitectura y ADR.",
            "acceptance": "Revisión explícita del arquitecto.",
        },
        "approval": {
            "kind": "direction_decision",
            "id": "project-case",
            "actor": "Stuart",
            "reference": "direction-session-1",
            "approved_at": 1.0,
            "request_sha256": request_sha256,
            "digest": decision_digest,
            "simulated": False,
        },
        "handoff": {
            "id": "opening:project-case:architecture",
            "from_actor": "meeting-assistant",
            "to_actor": "cloud-architect",
            "from_phase": "project-opening",
            "to_phase": "architecture",
            "revision": 1,
            "artifact_sha256": decision_digest,
            "created_at": 2.0,
            "accepted_at": None,
            "accepted_by": None,
        },
        "is_fictitious": False,
    }
    snapshot = {
        "provider": "github",
        "repository_url": repository_url,
        "number": 2,
        "url": f"{repository_url}/issues/2",
        "title": "[Arquitectura] AWS Cloud Consulting Project Demo",
        "state": "open",
        "assignees": ["cloud-architect"],
        "body": body,
        "retrieved_at": "2026-11-25T12:00:00-06:00",
    }
    return delivery, snapshot


def test_agent2_handoff_13_validates_transport_and_legacy_contracts(tmp_path):
    commit, inputs = project_repository(tmp_path)
    delivery, _ = handoff_v13(tmp_path, commit)

    context = ProjectRepositoryBridge().read(delivery)

    assert context["contract_version"] == "1.3"
    assert context["source_commit"] == commit
    assert context["request_sha256"] == delivery["request_sha256"]
    assert context["budget"]["total"] == "75.00"
    assert context["input_status"] == "awaiting_repository_validation"
    assert context["documents"] == []
    assert ProjectRepositoryBridge().read(handoff(tmp_path, commit, inputs))[
        "contract_version"
    ] == "1.1"


def test_agent2_handoff_13_rejects_wrong_issue_and_handoff_traceability(tmp_path):
    commit, _ = project_repository(tmp_path)
    delivery, _ = handoff_v13(tmp_path, commit)
    other = deepcopy(delivery)
    other["architecture_issue"]["url"] = (
        "https://github.com/example/other-project/issues/2"
    )
    with pytest.raises(ValidationError, match="issue pertenece a otro repositorio"):
        ProjectRepositoryBridge().read(other)
    wrong_handoff = deepcopy(delivery)
    wrong_handoff["handoff"]["artifact_sha256"] = "9" * 64
    with pytest.raises(ValidationError, match="handoff no corresponde"):
        ProjectRepositoryBridge().read(wrong_handoff)


def test_agent2_handoff_13_distinguishes_simulated_board_record(tmp_path):
    commit, _ = project_repository(tmp_path)
    delivery, _ = handoff_v13(tmp_path, commit)
    decision_digest = "8" * 64
    delivery["approval"] = {
        "kind": "board_record",
        "id": "board-1",
        "request_sha256": delivery["request_sha256"],
        "digest": decision_digest,
        "status": "approved",
        "closed_at": "2026-11-25T12:00:00-06:00",
        "review_url": "https://example.invalid/board/1",
        "simulated": True,
        "document_path": "docs/02-board/acta-junta-board-1.json",
        "document_sha256": "7" * 64,
        "signature_verification": "declared_by_source",
    }
    delivery["inputs"].append(
        {
            "path": "docs/02-board/acta-junta-board-1.json",
            "sha256": "7" * 64,
            "media_type": "application/json",
        }
    )
    delivery["handoff"]["artifact_sha256"] = decision_digest

    validated = ArchitectureProjectDelivery.model_validate(delivery)

    assert validated.approval.kind == "board_record"
    assert validated.approval.simulated is True
    assert validated.approval.signature_verification == "declared_by_source"


def test_agent2_handoff_13_binds_checkout_and_validates_issue_snapshot(tmp_path):
    commit, _ = project_repository(tmp_path)
    git(tmp_path, "remote", "add", "origin", "git@github.com:example/agent2-project.git")
    delivery, snapshot = handoff_v13(tmp_path, commit)
    context = ProjectRepositoryBridge().read(delivery)

    bound = ProjectRepositoryBridge().bind_repository(context, str(tmp_path))
    validated = ProjectRepositoryBridge.validate_issue(bound, snapshot)

    assert bound["input_status"] == "awaiting_issue_validation"
    assert bound["repository_binding"]["validation"] == "remote_commit_and_paths"
    assert bound["repository_binding"]["working_tree_modified"] is False
    assert validated["input_status"] == "ready_for_evidence_validation"
    assert validated["architecture_approved"] is False
    assert validated["issue_snapshot"]["state"] == "open"


def test_agent2_handoff_13_rejects_wrong_checkout_and_issue_evidence(tmp_path):
    commit, _ = project_repository(tmp_path)
    delivery, snapshot = handoff_v13(tmp_path, commit)
    context = ProjectRepositoryBridge().read(delivery)
    git(tmp_path, "remote", "add", "origin", "https://github.com/example/other.git")
    with pytest.raises(ValueError, match="otro repositorio"):
        ProjectRepositoryBridge().bind_repository(context, str(tmp_path))

    git(tmp_path, "remote", "set-url", "origin", delivery["repository"]["url"])
    bound = ProjectRepositoryBridge().bind_repository(context, str(tmp_path))
    wrong_assignee = {**snapshot, "assignees": ["another-architect"]}
    with pytest.raises(ValueError, match="arquitecto esperado"):
        ProjectRepositoryBridge.validate_issue(bound, wrong_assignee)
    changed = {**snapshot, "body": snapshot["body"] + "\nAlterado"}
    with pytest.raises(ValueError, match="cuerpo del issue cambió"):
        ProjectRepositoryBridge.validate_issue(bound, changed)


def test_closed_issue_is_evidence_but_not_architecture_approval(tmp_path):
    commit, _ = project_repository(tmp_path)
    git(tmp_path, "remote", "add", "origin", "https://github.com/example/agent2-project")
    delivery, snapshot = handoff_v13(tmp_path, commit)
    bridge = ProjectRepositoryBridge()
    bound = bridge.bind_repository(bridge.read(delivery), str(tmp_path))

    validated = bridge.validate_issue(bound, {**snapshot, "state": "closed"})

    assert validated["issue_snapshot"]["state"] == "closed"
    assert validated["architecture_approved"] is False


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


def test_service_persists_repository_and_issue_validation_steps(tmp_path):
    repo = tmp_path / "project"
    repo.mkdir()
    commit, _ = project_repository(repo)
    git(repo, "remote", "add", "origin", "https://github.com/example/agent2-project")
    delivery, snapshot = handoff_v13(repo, commit)
    connection, store, service = service_at(tmp_path / "state")
    try:
        assert service.read_project_handoff(delivery)["input_status"] == (
            "awaiting_repository_validation"
        )
        assert service.bind_project_repository("project-case", str(repo))[
            "input_status"
        ] == "awaiting_issue_validation"
        validated = service.validate_architecture_issue("project-case", snapshot)
        assert validated["input_status"] == "ready_for_evidence_validation"
        assert store.get("architecture-project-context:project-case") == validated
    finally:
        store.engine.dispose()
        connection.close()


@pytest.mark.parametrize("discovery_count", [3, 5, 6])
def test_contract_13_reads_supported_evidence_counts_from_exact_commit(
    tmp_path, discovery_count
):
    repo = tmp_path / f"project-{discovery_count}"
    repo.mkdir()
    commit, _ = project_repository(repo)
    git(repo, "remote", "add", "origin", "https://github.com/example/agent2-project")
    delivery, snapshot = handoff_v13(repo, commit, discovery_count)
    bridge = ProjectRepositoryBridge()
    context = bridge.validate_issue(
        bridge.bind_repository(bridge.read(delivery), str(repo)), snapshot
    )

    # A mutable working-tree edit must not affect evidence read from the approved commit.
    (repo / "docs/01-discovery/requirements.md").write_text(
        "contenido local no aprobado", encoding="utf-8"
    )
    validated = bridge.validate_evidence(context)

    assert validated["input_status"] == "evidence_validated"
    assert validated["evidence_manifest"]["discovery_count"] == discovery_count
    assert len(validated["documents"]) == discovery_count
    pdf = next(
        item for item in validated["documents"] if item["media_type"] == "application/pdf"
    )
    assert pdf["content"] is None and pdf["binary_omitted"] is True
    assert pdf["size_bytes"] > 0
    requirement = next(
        item
        for item in validated["documents"]
        if item["path"].endswith("requirements.md")
    )
    assert "Almacenar documentos" in requirement["content"]
    assert "contenido local" not in requirement["content"]


def test_contract_13_rejects_evidence_hash_mismatch(tmp_path):
    commit, _ = project_repository(tmp_path)
    git(tmp_path, "remote", "add", "origin", "https://github.com/example/agent2-project")
    delivery, snapshot = handoff_v13(tmp_path, commit)
    delivery["inputs"][0]["sha256"] = "0" * 64
    bridge = ProjectRepositoryBridge()
    context = bridge.validate_issue(
        bridge.bind_repository(bridge.read(delivery), str(tmp_path)), snapshot
    )

    with pytest.raises(ValueError, match="SHA-256 aprobado"):
        bridge.validate_evidence(context)


def test_contract_13_validates_delivery_manifest(tmp_path):
    commit, _ = project_repository(tmp_path)
    delivery, _ = handoff_v13(tmp_path, commit)
    files = [
        {"name": Path(item["path"]).name, "sha256": item["sha256"]}
        for item in delivery["inputs"]
    ]
    manifest = {
        "case_id": delivery["case_id"],
        "revision": 5,
        "files": files,
        "presentation_approval": {"revision": 4, "artifact_sha256": "6" * 64},
    }
    manifest_path = tmp_path / "docs/01-discovery/manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "Add approved manifest")
    commit = git(tmp_path, "rev-parse", "HEAD")
    git(tmp_path, "remote", "add", "origin", "https://github.com/example/agent2-project")
    delivery, snapshot = handoff_v13(tmp_path, commit)
    raw = git_bytes(tmp_path, "show", f"{commit}:docs/01-discovery/manifest.json")
    delivery["approved_package"].update(
        {
            "path": "docs/01-discovery/manifest.json",
            "sha256": hashlib.sha256(raw).hexdigest(),
            "files_sha256": hashlib.sha256(
                json.dumps(sorted(files, key=lambda item: item["name"]), sort_keys=True).encode()
            ).hexdigest(),
        }
    )
    bridge = ProjectRepositoryBridge()
    context = bridge.validate_issue(
        bridge.bind_repository(bridge.read(delivery), str(tmp_path)), snapshot
    )

    validated = bridge.validate_evidence(context)

    assert validated["evidence_manifest"]["manifest"]["revision"] == 5


def test_workflow_13_requires_evidence_then_interrupts_for_architect(tmp_path):
    repo = tmp_path / "project"
    repo.mkdir()
    commit, _ = project_repository(repo)
    git(repo, "remote", "add", "origin", "https://github.com/example/agent2-project")
    delivery, snapshot = handoff_v13(repo, commit)
    connection, store, service = service_at(tmp_path / "state")
    package = json.loads(DEFAULT_INPUT.read_text(encoding="utf-8"))
    package["project_id"] = delivery["project_id"]
    package["source_issue"] = delivery["architecture_issue"]["url"]
    package["requirements"][0]["source"] = delivery["inputs"][0]["path"]
    try:
        service.read_project_handoff(delivery)
        service.bind_project_repository("project-case", str(repo))
        service.validate_architecture_issue("project-case", snapshot)
        with pytest.raises(ValueError, match="todavía no validó"):
            service.start("project-case", commit, package)

        context = service.validate_project_evidence("project-case")
        started = service.start("project-case", commit, package)

        assert context["input_status"] == "evidence_validated"
        assert started["state"]["status"] == "awaiting_review"
        assert started["state"]["input_validation"]["status"] == "validated"
        assert started["pending"][0]["action"] == "architect_review"
        assert "decision" not in started["state"] or not started["state"]["decision"]
    finally:
        store.engine.dispose()
        connection.close()


def test_contract_13_records_human_decision_and_prepares_codex_pr_plan(tmp_path):
    repo = tmp_path / "project"
    repo.mkdir()
    commit, _ = project_repository(repo)
    git(repo, "remote", "add", "origin", "https://github.com/example/agent2-project")
    delivery, snapshot = handoff_v13(repo, commit)
    connection, store, service = service_at(tmp_path / "state")
    service.github_required = True
    package = json.loads(DEFAULT_INPUT.read_text(encoding="utf-8"))
    package["project_id"] = delivery["project_id"]
    package["source_issue"] = delivery["architecture_issue"]["url"]
    package["requirements"][0]["source"] = delivery["inputs"][0]["path"]
    try:
        service.read_project_handoff(delivery)
        service.bind_project_repository("project-case", str(repo))
        service.validate_architecture_issue("project-case", snapshot)
        service.validate_project_evidence("project-case")
        started = service.start("project-case", commit, package)["state"]
        receipt = {
            "contract_version": "1.0",
            "case_id": "project-case",
            "revision": 1,
            "artifact_sha256": started["artifact_sha256"],
            "decision": "approve",
            "feedback": "",
            "architect": "cloud-architect",
            "decided_at": "2026-11-25T14:00:00-06:00",
            "confirmation_source": "codex_conversation",
            "confirmation_reference": "codex-thread-step-9-message-1",
        }
        with pytest.raises(ValueError, match="recibo tipado"):
            service.review(
                "project-case", 1, started["artifact_sha256"], "approve"
            )
        wrong_actor = {**receipt, "architect": "another-user"}
        with pytest.raises(ValueError, match="arquitecto asignado"):
            service.record_architect_decision("project-case", wrong_actor)
        wrong_revision = {**receipt, "artifact_sha256": "0" * 64}
        with pytest.raises(ValueError, match="revisión pendiente exacta"):
            service.record_architect_decision("project-case", wrong_revision)

        recorded = service.record_architect_decision("project-case", receipt)
        assert recorded["duplicate"] is False
        assert recorded["state"]["status"] == "ready_for_finops"
        assert service.record_architect_decision("project-case", receipt)[
            "duplicate"
        ] is True
        changed_decision = {**receipt, "confirmation_reference": "another-message"}
        with pytest.raises(ValueError, match="otra decisión humana"):
            service.record_architect_decision("project-case", changed_decision)
        with pytest.raises(ValueError, match="espera aprobación"):
            service.get_finops_handoff("project-case", 1)

        branches_before = git(repo, "branch", "--format=%(refname:short)")
        publication = service.prepare_github_publication("project-case")
        plan = publication["plan"]
        assert plan["required_reviewer"] == "cloud-architect"
        assert plan["base_commit"] == commit
        assert plan["branch"] == "agent3/agent2-project/architecture-v001"
        assert "@cloud-architect" in plan["pull_request_body"]
        assert service.prepare_github_publication("project-case") == publication
        assert git(repo, "branch", "--format=%(refname:short)") == branches_before

        pr_receipt = {
            "contract_version": "1.0",
            "plan_sha256": publication["plan_sha256"],
            "repository_url": plan["repository_url"],
            "branch": plan["branch"],
            "base_branch": plan["base_branch"],
            "base_commit": plan["base_commit"],
            "commit_sha": "a" * 40,
            "files": [
                {"path": item["path"], "sha256": item["sha256"]}
                for item in plan["files"]
            ],
            "pull_request_number": 10,
            "pull_request_url": plan["repository_url"] + "/pull/10",
            "requested_reviewers": ["cloud-architect"],
            "state": "open",
            "created_at": "2026-11-25T14:05:00-06:00",
        }
        wrong_reviewer = {**pr_receipt, "requested_reviewers": ["another-user"]}
        with pytest.raises(ValueError, match="repositorio y rama planificados"):
            service.register_github_pull_request("project-case", wrong_reviewer)
        assert service.register_github_pull_request("project-case", pr_receipt)[
            "duplicate"
        ] is False
        assert service.register_github_pull_request("project-case", pr_receipt)[
            "duplicate"
        ] is True
        with pytest.raises(ValueError, match="espera aprobación"):
            service.get_finops_handoff("project-case", 1)
    finally:
        store.engine.dispose()
        connection.close()


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
    board_path = "docs/02-board/acta-junta-609a2ec8c4bf4045a0e9a2cd9f98e4e1.json"
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
    board_path = "docs/02-board/acta-junta-609a2ec8c4bf4045a0e9a2cd9f98e4e1.json"
    raw = git_bytes(NIKE_PROJECT, "show", f"{commit}:{board_path}")
    board = json.loads(raw)
    board["votes"][next(iter(board["votes"]))]["signature_verified"] = False

    with pytest.raises(ValidationError, match="no declara verificadas"):
        BoardRecord.model_validate(board)


def test_codex_github_boundary_requires_exact_pr_before_finops(tmp_path):
    repo = tmp_path / "project"
    repo.mkdir()
    commit, inputs = project_repository(repo)
    connection, store, service = service_at(tmp_path / "state")
    service.github_required = True
    context = service.read_project_handoff(handoff(repo, commit, inputs))
    package = json.loads(DEFAULT_INPUT.read_text(encoding="utf-8"))
    package["source_issue"] = context["architecture_issue_url"]
    package["requirements"][0]["source"] = "docs/01-discovery/requirements.md"
    started = service.start("project-case", commit, package)["state"]
    service.review("project-case", 1, started["artifact_sha256"], "approve")

    with pytest.raises(ValueError, match="espera aprobación"):
        service.get_finops_handoff("project-case", 1)

    publication = service.prepare_github_publication("project-case")
    plan = publication["plan"]
    receipt = {
        "contract_version": "1.0",
        "plan_sha256": publication["plan_sha256"],
        "repository_url": plan["repository_url"],
        "branch": plan["branch"],
        "base_branch": plan["base_branch"],
        "base_commit": plan["base_commit"],
        "commit_sha": "a" * 40,
        "files": [
            {"path": item["path"], "sha256": item["sha256"]} for item in plan["files"]
        ],
        "pull_request_number": 7,
        "pull_request_url": "https://github.com/example/documentos-demo/pull/7",
        "requested_reviewers": [plan["required_reviewer"]],
        "state": "open",
        "created_at": "2026-11-08T18:00:00-06:00",
    }
    tampered = deepcopy(receipt)
    tampered["files"][0]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="no contiene los artefactos"):
        service.register_github_pull_request("project-case", tampered)

    registered = service.register_github_pull_request("project-case", receipt)
    assert registered["duplicate"] is False
    assert (
        service.register_github_pull_request("project-case", receipt)["duplicate"]
        is True
    )
    observed = service.observe_github_event(
        "delivery-review-7",
        receipt["pull_request_url"],
        "pull_request_review",
        "submitted",
    )
    assert observed["status"] == "linked" and observed["approved"] is False
    assert not store.get("architecture-github-approval:project-case:1")
    approval = {
        "contract_version": "1.0",
        "plan_sha256": publication["plan_sha256"],
        "repository_url": plan["repository_url"],
        "pull_request_number": receipt["pull_request_number"],
        "pull_request_url": receipt["pull_request_url"],
        "head_sha": receipt["commit_sha"],
        "decision": "approved",
        "reviewer": plan["required_reviewer"],
        "review_id": "review-7",
        "reviewed_at": "2026-11-08T18:10:00-06:00",
        "checks": [
            {
                "name": "architecture-tests",
                "status": "completed",
                "conclusion": "success",
                "details_url": receipt["pull_request_url"] + "/checks/1",
            }
        ],
        "pull_request_state": "closed",
        "merged": True,
        "merged_at": "2026-11-08T18:11:00-06:00",
        "merge_commit_sha": "b" * 40,
        "source_issue_url": plan["source_issue_url"],
        "source_issue_state": "closed",
        "source_issue_closed_at": "2026-11-08T18:12:00-06:00",
        "evidence_source": "github_mcp",
        "observed_at": "2026-11-08T18:13:00-06:00",
        "github_delivery_id": None,
        "webhook_signature_verified": False,
    }
    wrong_reviewer_approval = {**approval, "reviewer": "another-user"}
    with pytest.raises(ValueError, match="PR y commit exactos"):
        service.register_github_approval("project-case", wrong_reviewer_approval)
    failed_checks = deepcopy(approval)
    failed_checks["checks"][0]["conclusion"] = "failure"
    with pytest.raises(ValidationError, match="success"):
        service.register_github_approval("project-case", failed_checks)
    unsigned_webhook = {
        **approval,
        "evidence_source": "github_webhook",
        "github_delivery_id": "delivery-7",
    }
    with pytest.raises(ValidationError, match="firma verificadas"):
        service.register_github_approval("project-case", unsigned_webhook)
    assert (
        service.register_github_approval("project-case", approval)["duplicate"] is False
    )
    with pytest.raises(ValueError, match="creación del issue FinOps"):
        service.get_finops_handoff("project-case", 1)

    draft = service.prepare_finops_issue("project-case", "finops-owner")
    assert approval["pull_request_url"] in draft["body"]
    issue_receipt = {
        "contract_version": "1.0",
        "plan_sha256": draft["plan_sha256"],
        "issue_url": "https://github.com/example/documentos-demo/issues/8",
        "issue_number": 8,
        "created_at": "2026-11-08T18:15:00-06:00",
        "body_sha256": draft["body_sha256"],
        "assignees": ["finops-owner"],
    }
    assert (
        service.register_finops_issue("project-case", issue_receipt)["duplicate"]
        is False
    )
    assert (
        service.register_finops_issue("project-case", issue_receipt)["duplicate"]
        is True
    )
    finops_handoff = service.get_finops_handoff("project-case", 1)
    received = FinOpsService(store).receive_handoff("project-case", finops_handoff)
    acceptance = received["intake"]["acceptance"]
    assert service.accept_finops_handoff("project-case", acceptance)[
        "duplicate"
    ] is False
    assert service.accept_finops_handoff("project-case", acceptance)[
        "duplicate"
    ] is True
    assert store.handoff("project-case:stage-3:stage-4:v1")["accepted_by"] == (
        "finops-agent"
    )
    store.engine.dispose()
    connection.close()
