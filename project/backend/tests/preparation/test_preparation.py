"""Verify durable review, replay protection and source-backed reference retrieval."""

import asyncio
import hashlib
import json
import sqlite3

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from mcp.server.mcpserver.exceptions import ToolError

from app.integrations.langgraph import LangGraphExecution
from app.mcp_server import create_server
from app.preparation.graph import build_graph
from app.preparation.references import REFERENCE_DIR, read_reference, search_references
from app.preparation.service import PreparationService


def service_at(path, search=search_references):
    connection = sqlite3.connect(path, check_same_thread=False)
    return connection, PreparationService(
        LangGraphExecution(build_graph(SqliteSaver(connection), search))
    )


def test_restarts_revisions_and_approval_preserve_one_handoff(tmp_path):
    path = tmp_path / "checkpoints.sqlite3"
    connection, service = service_at(path)
    started = service.start(
        "case-1", "event-1", "Necesitamos una tienda", "merchandising"
    )
    assert started["pending"][0]["action"] == "draft_with_chatgpt"
    assert started["state"]["references"][0]["project_id"].startswith("inter-miami")
    service.resume("case-1", "draft_with_chatgpt", "Primera propuesta")
    connection.close()

    connection, service = service_at(path)
    assert service.get("case-1")["state"]["draft"] == "Primera propuesta"
    revised = service.resume(
        "case-1", "manager_review", {"decision": "revise", "feedback": "Aclarar plazo"}
    )
    assert revised["pending"][0]["feedback"] == "Aclarar plazo"
    assert "handoff" not in revised["state"]
    service.resume("case-1", "draft_with_chatgpt", "Propuesta corregida")
    final = service.resume("case-1", "manager_review", {"decision": "approve"})
    assert final["pending"] == []
    assert final["state"]["handoff"]["draft"] == "Propuesta corregida"
    assert final["state"]["handoff"]["target_stage"] == 2
    metrics = service.metrics("case-1")
    assert metrics["lead_seconds"] >= metrics["measured_agent_process_seconds"] >= 0
    assert metrics["human_process_seconds"] is None
    assert metrics["rework_revisions"] == 1
    with pytest.raises(ValueError, match="estado actual"):
        service.resume("case-1", "manager_review", {"decision": "approve"})
    assert service.get("case-1")["state"]["handoff"] == final["state"]["handoff"]
    connection.close()


def test_duplicate_event_is_not_reprocessed_and_conflicting_input_is_rejected(tmp_path):
    calls = []

    def search(query):
        calls.append(query)
        return []

    connection, service = service_at(tmp_path / "state.sqlite3", search)
    first = service.start("case", "event", "Transcripción", "tienda")
    replay = service.start("case", "event", "Transcripción", "tienda")
    assert first == replay
    assert calls == ["tienda"]
    assert service.metrics("case")["lead_seconds"] is None
    with pytest.raises(ValueError, match="otra entrada"):
        service.start("case", "event", "Texto distinto", "tienda")
    with pytest.raises(ValueError, match="otra entrada"):
        service.start("case", "other-event", "Transcripción", "tienda")
    with pytest.raises(ValueError, match="estado actual"):
        service.resume("case", "manager_review", {"decision": "approve"})
    connection.close()


def test_no_match_is_empty_and_results_have_verifiable_evidence():
    assert search_references("xyznonexistent") == []
    matches = search_references("merchandising")
    assert matches and matches[0]["is_fictitious"]
    source = REFERENCE_DIR.parent / matches[0]["path"]
    assert matches[0]["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert matches[0]["evidence"]
    full = read_reference(matches[0]["project_id"])
    assert full["is_fictitious"] and len(full["documents"]) == 4
    with pytest.raises(ValueError, match="inexistente"):
        read_reference("../../project/secrets")
    manifest = json.loads((REFERENCE_DIR / "provenance.json").read_text())
    for item in manifest["files"]:
        content = (REFERENCE_DIR.parent / item["path"]).read_bytes()
        assert hashlib.sha256(content).hexdigest() == item["sha256"]


def test_mcp_exposes_the_workflow_and_rejects_premature_approval(tmp_path):
    connection, service = service_at(tmp_path / "mcp.sqlite3")
    service.start("case", "event", "Una tienda", "merchandising")
    server = create_server(service)

    async def exercise():
        tools = await server.list_tools()
        names = {tool.name for tool in tools}
        assert {
            "iniciar_preparacion",
            "guardar_borrador",
            "revisar_preparacion",
        } <= names
        with pytest.raises(ToolError, match="estado actual"):
            await server.call_tool(
                "revisar_preparacion", {"expediente_id": "case", "decision": "approve"}
            )
        assert "handoff" not in service.get("case")["state"]
        saved = await server.call_tool(
            "guardar_borrador", {"expediente_id": "case", "borrador": "Borrador"}
        )
        assert json.loads(saved.content[0].text)["state"]["status"] == "awaiting_review"
        approved = await server.call_tool(
            "revisar_preparacion", {"expediente_id": "case", "decision": "approve"}
        )
        assert (
            json.loads(approved.content[0].text)["state"]["status"]
            == "ready_for_stage_2"
        )

    asyncio.run(exercise())
    connection.close()
