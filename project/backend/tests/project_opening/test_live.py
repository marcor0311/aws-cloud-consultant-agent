"""Real MCP STDIO and durable LangGraph, with OAuth inference and GitHub offline."""

import json
import sys

import httpx
import pytest
from mcp import StdioServerParameters

from app.cli.agent2_live import execute_live
from app.integrations.ai.oauth import private_json
from app.integrations.ai.plan_session import PlanSession
from app.integrations.opening_mcp_client import OpeningMCPClient
from app.persistence.checkpoints import open_checkpointer
from app.persistence.workflow import WorkflowStore


@pytest.fixture
def bridge(tmp_path):
    script = tmp_path / "offline_mcp.py"
    script.write_text("""
from mcp.server.mcpserver import MCPServer
server = MCPServer("Offline GitHub Opening")
@server.tool()
def verificar_apertura(expediente_id: str) -> dict:
    return {"case_id": expediente_id, "request_sha256": "a"*64, "title": "Test"}
@server.tool()
def ejecutar_apertura(expediente_id: str, decision_sha256: str = "") -> dict:
    assert decision_sha256 == "a"*64
    return {"case_id": expediente_id, "status": "delivered",
            "repository": {"url": "https://github.invalid/offline/repo"},
            "commit": {"sha": "b"*40}, "issue": {"number": 1}}
server.run(transport="stdio")
""")
    return OpeningMCPClient(
        StdioServerParameters(command=sys.executable, args=[str(script)])
    )


def test_oauth_langgraph_mcp_and_saved_result_survive_restart(tmp_path, bridge):
    store = WorkflowStore(f"sqlite:///{tmp_path / 'workflow.sqlite3'}")
    session, requests = oauth_session(tmp_path)
    arguments = dict(
        case_id="nike-test",
        model="test",
        execution_id="live-test",
        allow_inference=True,
    )
    checkpoint = str(tmp_path / "checkpoints.sqlite3")
    with open_checkpointer(checkpoint) as saver:
        report = execute_live(store, saver, bridge, session, **arguments)
        assert report["status"] == "delivered"
        assert report["inference"]["response_id"] == "resp_test"
        assert report["mcp"]["transport"] == "stdio"
        assert report["mcp"]["server"]["name"] == "Offline GitHub Opening"
    with open_checkpointer(checkpoint) as saver:
        assert execute_live(store, saver, bridge, session, **arguments) == report
    assert len(requests) == 1
    assert store.get("agent2-live:live-test:report") == report
    session.client.close()
    store.engine.dispose()


def oauth_session(tmp_path):
    private_json(
        tmp_path / "registration.json",
        {"client_id": "test", "subject": "test", "ext_agent_host_id": "host"},
    )
    private_json(
        tmp_path / "session.json",
        {
            "client_id": "test",
            "subject": "test",
            "host_id": "host",
            "access_token": "oauth-test",
            "refresh_token": "",
            "expires_at": 9999999999,
        },
    )
    requests = []

    def respond(request):
        requests.append(request)
        assert request.headers["Authorization"] == "Bearer oauth-test"
        call = {
            "type": "function_call",
            "name": "ejecutar_apertura",
            "id": "fc_test",
            "call_id": "call_test",
            "status": "completed",
            "arguments": json.dumps(
                {"expediente_id": "nike-test", "decision_sha256": "a" * 64}
            ),
        }
        events = [
            {"type": "response.output_item.done", "output_index": 0, "item": call},
            {
                "type": "response.completed",
                "response": {
                    "id": "resp_test",
                    "status": "completed",
                    "model": "test",
                    "output": [],
                    "usage": {
                        "input_tokens": 20,
                        "output_tokens": 3,
                        "total_tokens": 23,
                    },
                },
            },
        ]
        return httpx.Response(
            200,
            text="\n\n".join("data: " + json.dumps(e) for e in events) + "\n\n",
            headers={"content-type": "text/event-stream"},
        )

    session = PlanSession(
        httpx.Client(transport=httpx.MockTransport(respond)),
        tmp_path,
        "http://127.0.0.1:8767/auth/callback",
    )
    return session, requests
