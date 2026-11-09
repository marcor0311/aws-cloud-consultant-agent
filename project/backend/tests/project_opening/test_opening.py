"""Approved bytes, real graph/checkpoint restart and remote idempotency, offline."""

import base64
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.cli.agent2_live import resolve_case
from app.integrations.langgraph import LangGraphExecution
from app.integrations.opening_documents import OpeningDocuments
from app.integrations.opening_preview import simulate_board_approval
from app.integrations.project_github import ProjectGitHub
from app.persistence.board_votes import BoardRepository
from app.persistence.checkpoints import open_checkpointer
from app.persistence.project_opening import ProjectOpeningRepository
from app.persistence.workflow import WorkflowStore
from app.preparation.deliveries import PreparationDeliveries
from app.preparation.graph import build_graph
from app.preparation.insumos import MeetingInsumos, MeetingTranscript
from app.preparation.local_intake import start_local_preparation
from app.preparation.service import PreparationService
from app.project_opening.board import BoardService
from app.project_opening.graph import build_opening_graph
from app.project_opening.service import OpeningService
from app.workflow.graph import build_process_graph
from app.workflow.service import ProcessService

ROOT = Path(__file__).resolve().parents[4]


TEMPLATE = ROOT / "project/agents/2. meeting assistant/templates/architecture.md"


FIXTURE = ROOT / "project/backend/fixtures/nike-lindora-stuart/opening.json"


class GitHub:
    def __init__(self):
        self.repositories, self.commits, self.issues = {}, {}, {}
        self.ref_reads, self.waits = 0, []
        self.merged = False
        self.merge_attempts = 0
        self.branch_created = False

    def ensure_repository(self, record):
        return self.repositories.setdefault(
            record["case_id"],
            {
                "url": f"https://github.com/example/{record['repository_name']}",
                "full_name": "example/" + record["repository_name"],
                "default_branch": "main",
                "id": 1,
            },
        )

    def publish(self, record, files):
        self.published = files

        def respond(request):
            path = request.url.path
            if request.method == "GET":
                if path.endswith("/git/ref/heads/docs/initial-structure"):
                    return (
                        httpx.Response(200, json={"object": {"sha": "0" * 40}})
                        if self.branch_created
                        else httpx.Response(404)
                    )
                if "/git/ref/" in path:
                    self.ref_reads += 1
                    if self.ref_reads == 1:
                        return httpx.Response(
                            409, json={"message": "Git Repository is empty."}
                        )
                    result = {"object": {"sha": "0" * 40}}
                elif "/git/commits/" in path:
                    result = {"tree": {"sha": "base"}}
                elif "/git/trees/" in path:
                    result = {"tree": []}
                else:
                    result = {"default_branch": "main"}
                return httpx.Response(200, json=result)
            if path.endswith("/git/refs"):
                assert (
                    json.loads(request.content)["ref"]
                    == "refs/heads/docs/initial-structure"
                )
                self.branch_created = True
            if request.method == "PATCH":
                assert path.endswith("/git/refs/heads/docs/initial-structure")
                assert json.loads(request.content)["force"] is False
            if path.endswith("/blobs"):
                data = base64.b64decode(json.loads(request.content)["content"])
                sha = hashlib.sha1(
                    b"blob " + str(len(data)).encode() + b"\0" + data
                ).hexdigest()
                return httpx.Response(201, json={"sha": sha})
            return httpx.Response(
                200 if request.method == "PATCH" else 201, json={"sha": "a" * 40}
            )

        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            commit = ProjectGitHub(
                client,
                lambda: "offline-token",
                wait=self.waits.append,  # gitleaks:allow -- offline mock
            ).publish(record, files)
        return self.commits.setdefault(record["case_id"], commit)

    def merge_initial_structure(self, record):
        marker = "<!-- " + ProjectGitHub.marker(record) + " -->"
        self.merge_attempts += 1

        def respond(request):
            if request.method == "PUT":
                assert json.loads(request.content)["sha"] == record["commit"]["sha"]
                if self.merge_attempts == 1:
                    return httpx.Response(405)
                self.merged = True
                return httpx.Response(200, json={"merged": True})
            pull = {
                "number": 1,
                "html_url": "https://github.com/example/repo/pull/1",
                "body": marker,
                "head": {"sha": record["commit"]["sha"]},
                "state": "closed" if self.merged else "open",
                "merged": self.merged,
                "merge_commit_sha": "b" * 40 if self.merged else None,
            }
            return httpx.Response(
                200, json=[pull] if request.url.path.endswith("/pulls") else pull
            )

        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            return ProjectGitHub(
                client, lambda: "offline-token"
            ).merge_initial_structure(record)

    def assign_architecture(self, record, body, template):
        assert self.merged
        self.body = body
        issue = self.issues.setdefault(
            record["case_id"],
            {
                "url": "https://github.com/example/repo/issues/1",
                "number": 1,
                "assignee": record.get("issue_assignee") or record["architect"],
            },
        )
        return issue


@pytest.fixture
def source(tmp_path):
    request = json.loads(FIXTURE.read_text())
    for file in request["files"]:
        value = ("Contenido ficticio " + file["name"]).encode()
        (tmp_path / file["name"]).write_bytes(value)
        file["sha256"] = hashlib.sha256(value).hexdigest()
    return request


def make_service(store, saver, github, directory):
    repo = ProjectOpeningRepository(store)
    docs = OpeningDocuments(directory, TEMPLATE)
    board = BoardService(BoardRepository(store), repo, None, store.clock)

    def gate(case_id):
        return board.require_approval(case_id, allow_simulated=True)

    class TestService(OpeningService):
        def register(self, value):
            seed_preparation(store, saver, value)
            result = super().register(value)
            simulate_board_approval(board, result["case_id"])
            return result

    return TestService(
        repo,
        LangGraphExecution(
            build_opening_graph(saver, repo, github, docs.files, docs.issue, gate)
        ),
        docs.validate,
        gate,
    )


def seed_preparation(store, saver, request):
    fixture = FIXTURE.parent
    transcript = MeetingTranscript.model_validate_json(
        (fixture / "transcript.json").read_text()
    )
    content = MeetingInsumos.model_validate_json((fixture / "content.json").read_text())
    process = ProcessService(
        LangGraphExecution(build_process_graph(saver)), store, request["approved_by"]
    )
    service = PreparationService(
        LangGraphExecution(
            build_graph(
                saver,
                drafter=lambda state: content.executive_package(transcript),
                store=store,
            )
        ),
        store,
        request["approved_by"],
        on_sync=process.sync_preparation,
        direction_actor="meeting-assistant",
        notifications=False,
    )
    runtime = SimpleNamespace(service=service, store=store, process=process)
    result = start_local_preparation(
        runtime, request["case_id"], transcript, provenance="offline_test"
    )
    revision = result["state"]["revision"]
    PreparationDeliveries(store).bind(request["case_id"], revision, request["files"])
    if result["state"]["status"] == "awaiting_review":
        store.accept_handoff(
            f"{request['case_id']}:preparation:stuart:v{revision}",
            request["approved_by"],
        )
        service.review(
            request["case_id"], revision, "approve", request["approval_reference"]
        )


def test_preparation_to_agent2_documents_issue_and_handoffs_persist(tmp_path, source):
    database = f"sqlite:///{tmp_path / 'workflow.sqlite3'}"
    checkpoint = str(tmp_path / "checkpoints.sqlite3")
    github = GitHub()
    store = WorkflowStore(database)
    with open_checkpointer(checkpoint) as saver:
        service = make_service(store, saver, github, tmp_path)
        approved = service.register(source)
        assert approved["title"] == "AWS Cloud Consulting Project Nike 01 Lindora Run"
        assert (
            approved["repository_name"]
            == "aws-cloud-consulting-project-nike-01-lindora-run"
        )
        assert resolve_case(store, None, "new-execution") == source["case_id"]
        assert store.get("opening-number:nike")["last"] == approved["project_number"]
        with pytest.raises(ValueError, match="initial_structure_merge_pending"):
            service.run(source["case_id"])
        assert (
            service.get(source["case_id"])["status"]
            == "awaiting_initial_structure_merge"
        )
        assert not github.issues
        assert service.run(source["case_id"])["status"] == "delivered"
        assert service.get(source["case_id"])["issue"]["assignee"] == "marcor0311"
        assert service.get(source["case_id"])["owner"] == "aws-cloud-consulting-group"
        assert github.ref_reads == 2 and github.waits == [1]
        assert resolve_case(store, None, "new-execution") is None
    store.engine.dispose()
    restarted = WorkflowStore(database)
    with open_checkpointer(checkpoint) as saver:
        service = make_service(restarted, saver, github, tmp_path)
        assert service.register(source)["project_number"] == 1
        result = service.run(source["case_id"])
        assert result["status"] == "delivered"
        assert service.run(source["case_id"]) == result
        assert (
            len(github.repositories) == len(github.commits) == len(github.issues) == 1
        )
        handoffs = restarted.case_handoffs(source["case_id"])
        assert len(handoffs) == 9
        assert all(
            h["accepted_at"] for h in handoffs if h["to_phase"] != "architecture"
        )
        assert not next(h for h in handoffs if h["to_phase"] == "architecture")[
            "accepted_at"
        ]
        audit = service.audit(source["case_id"])
        assert audit["source"]["provenance"] == "offline_test"
        assert audit["source"]["historical_occurred_at"] is None
        assert len([e for e in audit["events"] if e["kind"] == "handoff.created"]) == 9
        assert len([e for e in audit["events"] if e["kind"] == "handoff.accepted"]) == 8
        assert "Primera posición" not in github.body
        assert source["comments"] not in github.body
        assert "queue_position" not in github.body
        assert "180000" in github.body and "45000" in github.body
        assert "---\nname:" not in github.body
        assert "/blob/" + "a" * 40 + "/docs/01-discovery/" in github.body
        assert (
            len([p for p in github.published if p.startswith("docs/01-discovery/")])
            == 5
        )
        for file in source["files"]:
            assert (
                hashlib.sha256(
                    github.published["docs/01-discovery/" + file["name"]]
                ).hexdigest()
                == file["sha256"]
            )
    restarted.engine.dispose()
