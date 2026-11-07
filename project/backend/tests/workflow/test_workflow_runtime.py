"""Exercise the full Google event → agent tools → review → Slack path offline."""

import asyncio
import base64
import hashlib
import hmac
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import router
from app.api.dependencies import get_access_service, get_runtime
from app.bootstrap import create_runtime
from app.integrations.errors import ProviderError
from app.integrations.google_workspace import GoogleWorkspace
from app.integrations.slack import SlackNotifier
from app.mcp_server import create_server
from app.persistence.workflow import Busy, WorkflowStore
from app.workflow.settings import WorkflowSettings


def package():
    unknown = {"text": "No confirmado", "status": "unknown", "citations": []}
    return {
        "summary": "El cliente necesita una tienda de merchandising.",
        "needs": [
            {
                "text": "Tienda de merchandising",
                "status": "confirmed",
                "citations": [
                    {
                        "source_id": "transcript",
                        "quote": "Necesitamos una tienda de merchandising.",
                    }
                ],
            }
        ],
        "requirements": [],
        "budget": unknown,
        "timeline": unknown,
        "risks": [],
        "open_questions": ["¿Cuál es el presupuesto?"],
        "related_projects": [
            {
                "project_id": "inter-miami-merchandise-ecommerce",
                "reason": "Tienda ficticia del mismo tipo.",
                "citations": [
                    {
                        "source_id": "references/projects/inter-miami-merchandise-ecommerce/project-brief.md",
                        "quote": "merchandising",
                    }
                ],
            }
        ],
        "presentation": [
            {"title": "Necesidad", "bullets": ["Tienda de merchandising"]}
        ],
        "speaker_notes": "Confirmar presupuesto y plazo con el cliente.",
    }


class FakeClock:
    def __init__(self):
        self.now = 1793959200.0

    def __call__(self):
        return self.now


class Providers:
    def __init__(self, clock):
        self.clock = clock
        self.model_calls = 0
        self.slack_messages = []
        self.rate_limit = False
        self.timeout = False
        self.invalid_citation = False

    def handle(self, request):
        path = request.url.path
        if request.url.host == "api.openai.com":
            self.model_calls += 1
            self.clock.now += 1
            body = json.loads(request.content)
            assert body["store"] is False
            assert body["text"]["format"]["strict"] is True
            call = (self.model_calls - 1) % 3
            if call == 0:
                output = [
                    {
                        "type": "function_call",
                        "call_id": "search",
                        "name": "search_references",
                        "arguments": json.dumps({"query": "merchandising"}),
                    }
                ]
            elif call == 1:
                assert any(
                    m.get("type") == "function_call_output" for m in body["input"]
                )
                output = [
                    {
                        "type": "function_call",
                        "call_id": "read",
                        "name": "read_reference",
                        "arguments": json.dumps(
                            {"project_id": "inter-miami-merchandise-ecommerce"}
                        ),
                    }
                ]
            else:
                result = package()
                if self.invalid_citation:
                    result["needs"][0]["citations"][0]["quote"] = (
                        "invented client quote"
                    )
                output = [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": json.dumps(result)}
                        ],
                    }
                ]
            return httpx.Response(200, json={"status": "completed", "output": output})
        if request.url.host == "slack.com":
            if path.endswith("conversations.open"):
                return httpx.Response(
                    200, json={"ok": True, "channel": {"id": "DDEMO"}}
                )
            body = json.loads(request.content)
            if self.rate_limit:
                self.rate_limit = False
                return httpx.Response(429, headers={"Retry-After": "20"})
            self.slack_messages.append(body)
            if self.timeout:
                raise httpx.ReadTimeout("uncertain", request=request)
            return httpx.Response(
                200, json={"ok": True, "channel": "DDEMO", "ts": "123.456"}
            )
        if "/calendar/v3/" in path:
            return httpx.Response(
                200,
                json={
                    "id": "event-1",
                    "status": "confirmed",
                    "extendedProperties": {"private": {"calendar_assistant": "stuart"}},
                    "conferenceData": {"conferenceId": "abc-defg-hij"},
                    "start": {"dateTime": "2026-11-06T10:00:00Z"},
                    "end": {"dateTime": "2026-11-06T10:30:00Z"},
                },
            )
        if path.endswith("spaces/abc-defg-hij"):
            return httpx.Response(200, json={"name": "spaces/room-1"})
        if path == "/v1/subscriptions":
            if request.method == "GET":
                return httpx.Response(200, json={"subscriptions": []})
            return httpx.Response(
                200,
                json={
                    "done": True,
                    "response": {
                        "name": "subscriptions/sub-1",
                        "expireTime": "2026-11-07T10:00:00Z",
                    },
                },
            )
        if path.endswith("conferenceRecords/conf-1"):
            return httpx.Response(
                200,
                json={
                    "name": "conferenceRecords/conf-1",
                    "space": "spaces/room-1",
                    "startTime": "2026-11-06T10:00:00Z",
                    "endTime": "2026-11-06T10:30:00Z",
                },
            )
        if path.endswith("/transcripts"):
            if request.url.params.get("pageToken"):
                return httpx.Response(
                    200,
                    json={
                        "transcripts": [
                            {
                                "name": "conferenceRecords/conf-1/transcripts/t-2",
                                "state": "FILE_GENERATED",
                            }
                        ]
                    },
                )
            return httpx.Response(
                200,
                json={
                    "transcripts": [
                        {
                            "name": "conferenceRecords/conf-1/transcripts/t-1",
                            "state": "FILE_GENERATED",
                        }
                    ],
                    "nextPageToken": "second",
                },
            )
        if path.endswith("/entries"):
            if "/t-2/" in path:
                text = "No hay presupuesto aprobado."
            elif request.url.params.get("pageToken"):
                text = "El plazo sigue pendiente."
            else:
                return httpx.Response(
                    200,
                    json={
                        "transcriptEntries": [
                            {
                                "name": "entry-1",
                                "participant": "client",
                                "startTime": "2026-11-06T10:01:00Z",
                                "text": "Necesitamos una tienda de merchandising.",
                            }
                        ],
                        "nextPageToken": "more",
                    },
                )
            return httpx.Response(
                200,
                json={
                    "transcriptEntries": [
                        {
                            "name": text[:8],
                            "participant": "client",
                            "startTime": "2026-11-06T10:02:00Z",
                            "text": text,
                        }
                    ]
                },
            )
        raise AssertionError(f"Unexpected provider operation: {request.method} {path}")


@pytest.fixture
def runtime(tmp_path):
    clock = FakeClock()
    providers = Providers(clock)
    client = httpx.Client(transport=httpx.MockTransport(providers.handle))
    token = tmp_path / "fake-token.json"
    token.write_text("{}")
    google = GoogleWorkspace(token, client)
    google.credentials = SimpleNamespace(valid=True, token="fixture-only")
    settings = WorkflowSettings(
        database_url=f"sqlite:///{tmp_path / 'workflow.sqlite3'}",
        checkpoint_url=str(tmp_path / "checkpoints.sqlite3"),
        enabled=True,
        openai_key="fixture",
        openai_model="fixture-model",
        slack_token="fixture",
        slack_user_id="UDEMO",
        pubsub_topic="projects/demo/topics/meet",
        github_secret="s" * 32,
        github_repositories=("demo/repo",),
    )
    workflow = create_runtime(
        settings,
        google=google,
        notifier=SlackNotifier("fixture", "UDEMO", client),
        clock=clock,
    )
    workflow.drafter.client = client
    try:
        yield workflow, providers, clock
    finally:
        workflow.close()


def message(event_id="event-1"):
    return {
        "messageId": event_id,
        "attributes": {
            "ce-id": event_id,
            "ce-type": "google.workspace.meet.transcript.v2.fileGenerated",
            "ce-source": "//workspaceevents.googleapis.com/subscriptions/sub-1",
        },
        "data": base64.b64encode(
            json.dumps(
                {"transcript": {"name": "conferenceRecords/conf-1/transcripts/t-1"}}
            ).encode()
        ).decode(),
    }


def scheduled(runtime):
    case = runtime.register_meeting(
        {
            "calendar_id": "primary",
            "calendar_event_id": "event-1",
            "operation": "scheduled",
            "version": "v1",
        },
        42,
    )["case_id"]
    assert runtime.run_once()
    assert runtime.store.get(f"meeting:{case}")["status"] == "scheduled"
    return case


def ready(runtime):
    case = scheduled(runtime)
    assert runtime.receive_message(message())["status"] == "accepted"
    assert runtime.run_once()
    return case


def test_complete_event_tool_loop_slack_revision_approval_and_metrics(runtime):
    workflow, providers, clock = runtime
    case = ready(workflow)
    state = workflow.service.get(case)
    assert workflow.process.get(case)["state"]["status"] == "awaiting_review"
    assert state["pending"][0]["action"] == "manager_review"
    assert state["state"]["package"]["budget"]["status"] == "unknown"
    assert "handoff" not in state["state"]
    assert providers.model_calls == 3
    assert len(workflow.store.list("reference")) == 48
    assert (
        "No hay presupuesto aprobado"
        in workflow.store.get(f"transcript:{case}")["text"]
    )
    assert (
        "El plazo sigue pendiente" in workflow.store.get(f"transcript:{case}")["text"]
    )
    assert workflow.run_once()  # Slack after the draft is durably ready.
    assert len(providers.slack_messages) == 1
    assert "transcripción" not in providers.slack_messages[0]["text"]
    assert workflow.receive_message(message())["status"] == "duplicate"
    workflow.receive_message(message("second-event-same-conference"))
    workflow.run_once()
    assert providers.model_calls == 3
    assert len(providers.slack_messages) == 1
    with pytest.raises(ValueError, match="revisión cambió"):
        workflow.service.review(case, 0, "approve")
    human = workflow.store.start_work(
        case, "preparation", workflow.settings.manager_id, "human"
    )
    clock.now += 5
    workflow.store.stop_work(human, workflow.settings.manager_id)
    workflow.service.review(case, 1, "revise", "Aclarar los pendientes")
    assert providers.model_calls == 6
    assert workflow.service.get(case)["state"]["revision"] == 2
    final = workflow.service.review(case, 2, "approve")
    assert final["state"]["status"] == "ready_for_stage_2"
    assert workflow.process.get(case)["state"]["stage"] == 2
    assert (
        workflow.store.get(f"handoff:{case}")["receipt"]
        == "awaiting_stage_2_acceptance"
    )
    assert "# Guion" in workflow.artifact(case, "speaker-notes.md", 2)["content"]
    metrics = workflow.service.metrics(case)["phases"][0]
    assert metrics["recorded_effort_seconds"] == {"human": 5.0, "agent": 6.0}
    assert metrics["lead_seconds"] >= metrics["process_union_seconds"]


def test_backend_queues_and_separate_worker_processes_registered_meeting(
    runtime, monkeypatch
):
    import app.main as application

    workflow, providers, _ = runtime
    monkeypatch.setenv("WORKFLOW_ENABLED", "1")
    monkeypatch.setenv("CALENDAR_ACCESS_SERVICE_KEY", "k" * 32)
    monkeypatch.setattr(application, "clear_runtime", lambda: None)
    contact = SimpleNamespace(
        client_id=42, company_email="client@example.test", enabled=True
    )
    access = SimpleNamespace(
        authorize=lambda *_: {"status": "authorized", "email": contact.company_email},
        clients=SimpleNamespace(lookup_code=lambda _: contact),
    )
    application.app.dependency_overrides[get_runtime] = lambda: workflow
    application.app.dependency_overrides[get_access_service] = lambda: access
    try:
        with TestClient(application.app) as client:
            response = client.post(
                "/api/calendar-access/meeting",
                headers={"Authorization": "Bearer " + "k" * 32},
                json={
                    "session_id": "session-" + "a" * 32,
                    "client_code": "DEMO-0001",
                    "email": contact.company_email,
                    "calendar_id": "primary",
                    "calendar_event_id": "event-1",
                    "operation": "scheduled",
                    "version": "v1",
                },
            )
            assert response.status_code == 200
            case = response.json()["case_id"]
            # HTTP only commits the task. The separate worker owns integrations and AI.
            assert not workflow.store.get("subscription:spaces/room-1")
            assert providers.model_calls == 0
            assert workflow.run_once()
            assert workflow.process.get(case)["state"]["status"] == "awaiting_meeting"
            workflow.receive_message(message())
            assert workflow.run_once()
            assert workflow.run_once()
            assert workflow.service.get(case)["state"]["status"] == "awaiting_review"
            assert len(providers.slack_messages) == 1
            assert client.get("/api/workflow/cases").status_code in {401, 503}
    finally:
        application.app.dependency_overrides.clear()


def test_slack_rate_limit_and_ambiguous_send_do_not_create_duplicates(runtime):
    workflow, providers, clock = runtime
    case = ready(workflow)
    providers.rate_limit = True
    workflow.run_once()
    notice = f"notice:{case}:1:awaiting_review"
    assert workflow.store.job(notice)["status"] == "pending"
    assert not workflow.run_once()
    clock.now += 30
    providers.timeout = True
    workflow.run_once()
    assert workflow.store.job(notice)["status"] == "uncertain"
    clock.now += 1000
    assert not workflow.run_once()
    assert len(providers.slack_messages) == 1


def test_invalid_model_evidence_cannot_reach_review_or_slack(runtime):
    workflow, providers, _ = runtime
    providers.invalid_citation = True
    case = ready(workflow)
    assert workflow.service.get(case)["state"].get("status") != "awaiting_review"
    assert workflow.store.get(f"artifact:{case}:1") is None
    assert providers.slack_messages == []


def test_failed_model_run_resumes_from_checkpoint_after_restart(runtime):
    workflow, providers, clock = runtime
    providers.invalid_citation = True
    case = ready(workflow)
    settings, google, notifier, client = (
        workflow.settings,
        workflow.google,
        workflow.notifier,
        workflow.drafter.client,
    )
    workflow.close()
    providers.invalid_citation = False
    clock.now += 60
    restarted = create_runtime(settings, google=google, notifier=notifier, clock=clock)
    restarted.drafter.client = client
    try:
        assert restarted.run_once()
        assert restarted.service.get(case)["state"]["status"] == "awaiting_review"
        assert restarted.service.get(case)["state"]["revision"] == 1
        assert restarted.run_once()
        assert len(providers.slack_messages) == 1
    finally:
        restarted.close()


def test_async_workspace_subscription_is_retained_when_done_is_omitted(
    runtime, monkeypatch
):
    workflow, _, _ = runtime
    monkeypatch.setattr(workflow.google, "find_subscriptions", lambda _: [])
    monkeypatch.setattr(
        workflow.google, "subscribe", lambda *_: {"name": "operations/create-1"}
    )
    with pytest.raises(ProviderError, match="pending"):
        workflow.ensure_subscription("spaces/room-1")
    assert (
        workflow.store.get("subscription:spaces/room-1")["operation"]
        == "operations/create-1"
    )
    monkeypatch.setattr(
        workflow.google,
        "operation",
        lambda _: {
            "done": True,
            "response": {
                "name": "subscriptions/sub-1",
                "expireTime": "2026-11-07T10:00:00Z",
            },
        },
    )
    assert (
        workflow.ensure_subscription("spaces/room-1")["name"] == "subscriptions/sub-1"
    )


def test_http_ingestion_auth_and_github_observation_do_not_invent_process_time(
    runtime, monkeypatch
):
    workflow, _, _ = runtime
    case = scheduled(workflow)
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_runtime] = lambda: workflow
    client = TestClient(app)
    monkeypatch.setenv("WORKFLOW_PUSH_AUDIENCE", "https://example.test/meet")
    monkeypatch.setenv("WORKFLOW_PUSH_SERVICE_ACCOUNT", "push@example.test")
    assert (
        client.post(
            "/api/workflow/events/meet", json={"message": message()}
        ).status_code
        == 401
    )
    monkeypatch.setattr(
        "app.api.webhooks.id_token.verify_oauth2_token",
        lambda *_: {"email": "push@example.test", "email_verified": True},
    )
    result = client.post(
        "/api/workflow/events/meet",
        json={"message": message()},
        headers={"Authorization": "Bearer fixture"},
    )
    assert result.status_code == 202
    issue_url = "https://github.com/demo/repo/issues/7"
    workflow.store.phase(case, "stage-3", workflow.settings.manager_id, issue_url)
    raw = json.dumps(
        {
            "repository": {"full_name": "demo/repo"},
            "action": "closed",
            "issue": {
                "html_url": issue_url,
                "closed_at": "2026-11-06T10:00:00Z",
                "labels": [],
            },
        }
    ).encode()
    headers = {
        "X-Github-Event": "issues",
        "X-Github-Delivery": "delivery-1",
        "X-Hub-Signature-256": "sha256="
        + hmac.new(b"s" * 32, raw, hashlib.sha256).hexdigest(),
    }
    assert client.post("/api/workflow/events/github", content=raw).status_code == 401
    assert (
        client.post(
            "/api/workflow/events/github", content=raw, headers=headers
        ).status_code
        == 202
    )
    assert (
        client.post(
            "/api/workflow/events/github", content=raw, headers=headers
        ).status_code
        == 202
    )
    phase = next(
        p for p in workflow.store.metrics(case)["phases"] if p["phase"] == "stage-3"
    )
    assert phase["completed_at"] is None
    assert phase["recorded_effort_seconds"]["human"] == 0


def test_review_rework_is_audited_even_if_redrafting_fails(runtime):
    workflow, providers, _ = runtime
    case = ready(workflow)
    providers.invalid_citation = True
    with pytest.raises(ProviderError):
        workflow.service.review(case, 1, "revise", "Aclarar presupuesto desconocido")
    assert workflow.service.metrics(case)["rework_cycles"] == 1
    assert workflow.store.get(f"handoff:{case}") is None
    providers.invalid_citation = False
    result = workflow.service.continue_preparation(case)
    assert result["state"]["revision"] == 2
    assert result["pending"][0]["action"] == "manager_review"


def test_mcp_redraft_is_queued_and_worker_recovers_failed_model_node(runtime):
    workflow, providers, clock = runtime
    case = ready(workflow)
    workflow.run_once()  # Deliver the initial notification.
    server = create_server(workflow.service, workflow)

    async def request_changes():
        return await server.call_tool(
            "revisar_preparacion",
            {
                "expediente_id": case,
                "decision": "revise",
                "revision": 1,
                "comentarios": "Aclarar presupuesto desconocido",
            },
        )

    response = asyncio.run(request_changes())
    receipt = json.loads(response.content[0].text)
    assert receipt["status"] == "pending"
    assert providers.model_calls == 3
    providers.invalid_citation = True
    workflow.run_once()
    assert workflow.store.job(receipt["task_id"])["status"] == "pending"
    assert workflow.service.get(case)["state"]["status"] == "awaiting_draft"
    assert workflow.process.get(case)["state"]["status"] == "preparing"
    providers.invalid_citation = False
    clock.now += 31
    workflow.run_once()
    assert workflow.store.job(receipt["task_id"])["status"] == "done"
    assert workflow.service.get(case)["state"]["revision"] == 2
    process = workflow.process.get(case)["state"]
    assert process["status"] == "awaiting_review" and process["rework_cycles"] == 1


def test_http_and_mcp_use_same_process_service_and_explicit_approval(
    runtime, monkeypatch
):
    workflow, providers, _ = runtime
    case = ready(workflow)
    workflow.run_once()
    workflow.service.review(case, 1, "approve")
    workflow.run_once()
    token = "operator-fixture-" + "a" * 32
    monkeypatch.setenv("WORKFLOW_MANAGER_TOKEN", token)
    application = FastAPI()
    application.include_router(router, prefix="/api")
    application.dependency_overrides[get_runtime] = lambda: workflow
    client = TestClient(application)
    path = f"/api/workflow/cases/{case}/process"
    assert client.get(path).status_code == 401
    headers = {"Authorization": "Bearer " + token}
    state = client.get(path, headers=headers).json()["state"]
    assert state["stage"] == 2
    body = {
        "event_id": "board-approval",
        "kind": "stage.approved",
        "stage": 2,
        "iteration": state["iteration"],
        "revision": state["revision"],
        "artifact_sha256": state["artifact_sha256"],
    }
    response = client.post(path + "/events", headers=headers, json=body)
    assert response.status_code == 202
    assert workflow.process.get(case)["state"]["stage"] == 2
    workflow.run_once()
    server = create_server(workflow.service, workflow)
    result = asyncio.run(server.call_tool("consultar_proceso", {"expediente_id": case}))
    assert json.loads(result.content[0].text)["state"]["stage"] == 3
    assert providers.model_calls == 3  # Moving a stage does not invoke a model.
    body["event_id"] = "stale-board-approval"
    assert client.post(path + "/events", headers=headers, json=body).status_code == 409


def test_mcp_reads_same_durable_case_and_approved_artifacts(runtime):
    workflow, _, _ = runtime
    case = ready(workflow)
    server = create_server(workflow.service, workflow)

    async def exercise():
        result = await server.call_tool(
            "consultar_preparacion", {"expediente_id": case}
        )
        assert (
            json.loads(result.content[0].text)["state"]["status"] == "awaiting_review"
        )
        result = await server.call_tool(
            "revisar_preparacion",
            {"expediente_id": case, "decision": "approve", "revision": 1},
        )
        assert (
            json.loads(result.content[0].text)["state"]["status"] == "ready_for_stage_2"
        )
        result = await server.call_tool(
            "consultar_insumo",
            {"expediente_id": case, "nombre": "executive-summary.md", "revision": 1},
        )
        assert (
            "Tienda de merchandising" in json.loads(result.content[0].text)["content"]
        )

    asyncio.run(exercise())


def test_database_leases_and_overlapping_effort_are_not_double_counted(tmp_path):
    clock = FakeClock()
    store = WorkflowStore(f"sqlite:///{tmp_path / 'db.sqlite3'}", clock)
    store.phase("case", "stage-3", "manager")
    first = store.start_work("case", "stage-3", "manager", "human")
    clock.now += 2
    second = store.start_work("case", "stage-3", "agent", "agent")
    clock.now += 3
    store.stop_work(first, "manager")
    clock.now += 2
    store.stop_work(second, "agent")
    store.complete_phase("case", "stage-3")
    phase = store.metrics("case")["phases"][0]
    assert phase["lead_seconds"] == 7
    assert phase["process_union_seconds"] == 7
    assert sum(phase["recorded_effort_seconds"].values()) == 10
    with store.lock("case"):
        with pytest.raises(Busy):
            with store.lock("case"):
                pass
    store.engine.dispose()
