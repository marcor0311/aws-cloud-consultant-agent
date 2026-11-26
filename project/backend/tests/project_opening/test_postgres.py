"""Actual PostgreSQL persistence and LangGraph recovery in an isolated test DB."""

import asyncio
import json
import os
import shutil
import uuid
from pathlib import Path

import pytest

from app.bootstrap import create_document_preparation_runtime, create_opening_runtime
from app.cli.preparation_documents import reconcile_approved_preparation
from app.demos.workflow import run_demo
from app.integrations.opening_documents import OpeningDocuments
from app.integrations.opening_preview import simulate_board_approval
from app.preparation.insumos import MeetingInsumos, MeetingTranscript
from app.project_opening.mcp import create_server

ROOT = Path(__file__).resolve().parents[4]


@pytest.mark.postgres
@pytest.mark.skipif(
    not os.getenv("WORKFLOW_TEST_POSTGRES_URL"),
    reason="isolated PostgreSQL URL not configured",
)
def test_postgres_queue_checkpoints_and_handoff_survive_restart(tmp_path):
    request = json.loads(
        (ROOT / "project/backend/fixtures/nike-lindora-stuart/opening.json").read_text()
    )
    request["case_id"] = "pg-" + uuid.uuid4().hex
    request["company"] = "Test " + uuid.uuid4().hex[:8]
    source = tmp_path / "inputs"
    source.mkdir()
    for file in request["files"]:
        shutil.copy2(
            ROOT / "insumos temporales de agente 1" / file["name"],
            source / file["name"],
        )
    template = ROOT / "project/agents/2. meeting assistant/templates/architecture.md"
    calls = []

    class GitHub:
        def find_user(self, login):
            return login

        def ensure_repository(self, record):
            return {
                "url": "https://github.com/test/repo",
                "full_name": "test/repo",
                "default_branch": "main",
            }

        def publish(self, record, files):
            return {
                "sha": "b" * 40,
                "url": "https://github.com/test/repo/commit/" + "b" * 40,
            }

        def merge_initial_structure(self, record):
            return {"number": 1, "merged": True, "merge_sha": record["commit"]["sha"]}

        def assign_architecture(self, record, body, template):
            if not calls:
                calls.append(record["case_id"])
            return {
                "number": 1,
                "url": "https://github.com/test/repo/issues/1",
                "assignee": record["issue_assignee"],
            }

    github = GitHub()
    url = os.environ["WORKFLOW_TEST_POSTGRES_URL"]
    reconciled = reconcile_approved_preparation(url, request, source=source)
    fixture = ROOT / "project/backend/fixtures/nike-lindora-stuart"
    preparation = create_document_preparation_runtime(
        url,
        MeetingTranscript.model_validate_json(
            (fixture / "transcript.json").read_text()
        ),
        MeetingInsumos.model_validate_json((fixture / "content.json").read_text()),
        manager_id=request["approved_by"],
    )
    try:
        assert reconciled["review_subject"] == "speaker_notes"
        preparation.service.begin_review(request["case_id"], reconciled["revision"])
        preparation.service.review(
            request["case_id"],
            reconciled["revision"],
            "approve",
            "Guion aprobado en prueba.",
        )
        exported = OpeningDocuments(
            source, template, preparation.store
        ).export_preparation(request["case_id"], reconciled["revision"])
        request["files"] = exported["files"]
    finally:
        preparation.close()
    first = create_opening_runtime(
        url, source, template, github=github, simulated_board_case=request["case_id"]
    )
    try:
        first.service.register(request)
        simulate_board_approval(first.board, request["case_id"])
        assert first.service.run(request["case_id"])["status"] == "delivered"
    finally:
        first.close()
    second = create_opening_runtime(
        url, source, template, github=github, simulated_board_case=request["case_id"]
    )
    try:
        assert second.store.engine.dialect.name == "postgresql"
        assert second.service.get(request["case_id"])["status"] == "delivered"
        assert second.service.run(request["case_id"])["status"] == "delivered"
        assert len(calls) == 1
        handoffs = second.store.case_handoffs(request["case_id"])
        assert len(handoffs) == 10
        assert sum(h["accepted_at"] is not None for h in handoffs) == 9
        assert (
            next(
                r for r in second.service.queue() if r["case_id"] == request["case_id"]
            )["queue_position"]
            == 1
        )
    finally:
        second.close()

    # The existing Agent 1 mock journey now hands its PostgreSQL-persisted,
    # six-file approval to the guided Agent 2 MCP flow in the same database.
    demo_dir = tmp_path / "agent1-to-agent2"
    report = run_demo(
        demo_dir,
        collaborate=True,
        database_url=url,
        checkpoint_url=url,
    )
    assert report["external_connections"] == []
    approved = next(
        project
        for project in report["projects"]
        if project["status"] == "ready_for_stage_2"
    )
    source = demo_dir / "mock-presentation"
    mcp_runtime = create_opening_runtime(
        url,
        source,
        ROOT / "project/agents/2. meeting assistant/templates/architecture.md",
        github=github,
        approval_mode="direction",
    )
    try:
        server = create_server(
            mcp_runtime.service,
            conversation=mcp_runtime.conversation,
        )

        async def call_tool(name, arguments=None):
            result = await server.call_tool(name, arguments or {})
            return json.loads(result.content[0].text)

        started = asyncio.run(call_tool("iniciar_apertura_guiada"))
        assert started["field"] == "project"
        assert any(p["case_id"] == approved["case_id"] for p in started["projects"])
        session = started["session_id"]

        def answer(value):
            return asyncio.run(
                call_tool(
                    "responder_apertura_guiada",
                    {"sesion_id": session, "respuesta": value},
                )
            )

        assert answer(approved["case_id"])["field"] == "approved"
        assert answer("sí")["field"] == "queue_position"
        assert answer("1")["field"] == "budget"
        assert answer("12000")["field"] == "architect"
        confirmation = answer("CloudArchitectMock")
        assert confirmation["field"] == "confirm_creation"
        assert confirmation["summary"]["files_to_publish"] == 6

        manifest = mcp_runtime.store.get(
            f"artifact-files:{approved['case_id']}:{approved['revision']}"
        )
        saved_package = mcp_runtime.store.get(
            f"approved-package:{approved['case_id']}:{approved['revision']}"
        )
        assert saved_package["files_sha256"] == manifest["files_sha256"]
        assert len(saved_package["contents"]) == 7

        result = answer("sí")
        assert result["status"] == "delivered"
        opening = mcp_runtime.service.get(approved["case_id"])
        assert opening["architect"] == "CloudArchitectMock"
        assert opening["budget"]["total"] == "12000.00"
        assert opening["repository"]["full_name"]
        assert opening["issue"]["assignee"] == "CloudArchitectMock"
    finally:
        mcp_runtime.close()
