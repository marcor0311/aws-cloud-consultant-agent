"""Browser caption ingestion uses actual HTTP, SQL, queue and LangGraph; no cloud."""

import asyncio
import hashlib
import json
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient
from google.auth.exceptions import RefreshError

from app.api.dependencies import get_runtime
from app.bootstrap import create_runtime
from app.cli import workflow as workflow_cli
from app.integrations.ai.chatgpt_preparer import ChatGPTPreparer
from app.integrations.ai.oauth import private_json
from app.integrations.ai.plan_session import PlanSession
from app.integrations.google_workspace import GoogleWorkspace
from app.integrations.langgraph import LangGraphExecution
from app.integrations.mcp_http import BearerProtectedMCP
from app.main import app
from app.mcp_server import create_server
from app.persistence.checkpoints import open_checkpointer
from app.preparation.graph import build_graph
from app.preparation.processing import ProcessedMeeting
from app.preparation.service import PreparationService
from app.project_opening.models import ApprovedFile
from app.workflow.runtime import timestamp
from app.workflow.settings import WorkflowSettings
from app.workflow.transcripts import receive_capture

KEY = "offline-transcript-only-key-12345678901234567890"


def capture(**changes):
    return {
        "capture_id": "41cd930a-a017-4bca-82bc-a9957b3b9344",
        "meeting_url": "https://meet.google.com/abc-defg-hij",
        "started_at": "2026-11-09T16:00:00Z",
        "ended_at": "2026-11-09T16:20:00Z",
        "reporter_name": "Stuart",
        "segments": [
            {
                "speaker": "Stuart",
                "at": "2026-11-09T16:00:10Z",
                "text": "¿Qué necesitan?",
            },
            {
                "speaker": "Ana",
                "at": "2026-11-09T16:01:00Z",
                "text": "Una aplicación para ventas.",
            },
            {
                "speaker": "Luis",
                "at": "2026-11-09T16:02:00Z",
                "text": "Tenemos cuatro sucursales.",
            },
            {
                "speaker": "María",
                "at": "2026-11-09T16:03:00Z",
                "text": "El presupuesto está por confirmar.",
            },
        ],
        **changes,
    }


@pytest.fixture
def ready(tmp_path):
    settings = WorkflowSettings(
        database_url=f"sqlite:///{tmp_path / 'workflow.sqlite3'}",
        checkpoint_url=str(tmp_path / "checkpoints.sqlite3"),
        enabled=True,
        documents_dir=tmp_path / "documents",
    )
    google, drafter = Mock(), Mock(side_effect=AssertionError("No inline inference"))
    google.calendar_event.return_value = {
        "summary": "Inicial",
        "status": "confirmed",
        "extendedProperties": {"private": {"calendar_assistant": "stuart"}},
        "conferenceData": {"conferenceId": "abc-defg-hij"},
        "start": {"dateTime": "2026-11-09T16:00:00Z"},
        "end": {"dateTime": "2026-11-09T16:30:00Z"},
    }
    runtime = create_runtime(
        settings,
        google=google,
        drafter=drafter,
        clock=lambda: timestamp("2026-11-09T17:00:00Z"),
    )
    try:
        yield runtime, google, drafter
    finally:
        runtime.close()


def test_authenticated_api_queues_then_worker_preserves_speakers_after_restart(
    ready, monkeypatch, tmp_path, capsys, caplog
):
    runtime, google, drafter = ready
    # A rejected Google renewal must explain the failure through the real queue,
    # then allow synchronization and transcript processing after authorization.
    token_file = tmp_path / "google-token.json"
    token_file.touch()
    credentials = Mock(valid=False)
    credentials.refresh.side_effect = RefreshError(
        "private-provider-response",
        {"error": "invalid_grant", "error_description": "private-provider-response"},
    )
    google_http = Mock()
    runtime.google = GoogleWorkspace(token_file, client=google_http)
    with monkeypatch.context() as patch:
        patch.setattr(
            "app.integrations.google_workspace.Credentials.from_authorized_user_file",
            Mock(return_value=credentials),
        )
        runtime.store.receive(
            "oauth-calendar-sync", "calendar_sync", {"calendar_id": "primary"}
        )
        assert runtime.run_once()
    failed = runtime.store.job("oauth-calendar-sync")
    assert failed["status"] == "failed"
    assert failed["error"] == "google_oauth_refresh_rejected"
    assert "Google OAuth" in caplog.text
    assert "invalid_grant" in caplog.text
    assert "make calendar-auth" in caplog.text
    assert "tipo=calendar_sync" in caplog.text
    assert "private-provider-response" not in caplog.text
    google_http.request.assert_not_called()
    runtime.google = google
    google.calendar_changes.return_value = {"items": [], "nextSyncToken": "offline"}
    runtime.store.finish_job("oauth-calendar-sync", status="pending")
    assert runtime.run_once()
    assert runtime.store.job("oauth-calendar-sync")["status"] == "done"
    monkeypatch.setenv("WORKFLOW_TRANSCRIPT_TOKEN", KEY)
    app.dependency_overrides[get_runtime] = lambda: runtime
    try:
        with TestClient(app) as api:
            assert (
                api.post("/api/workflow/events/transcript", json=capture()).status_code
                == 401
            )
            result = api.post(
                "/api/workflow/events/transcript",
                json=capture(),
                headers={"Authorization": f"Bearer {KEY}"},
            )
            assert result.status_code == 202
            assert runtime.store.list("transcript") == []
        other = create_runtime(
            runtime.settings, google=google, drafter=drafter, clock=runtime.store.clock
        )
        try:
            assert other.run_once()
            waiting = other.store.job(result.json()["task_id"])
            assert waiting["status"] == "pending"
            assert waiting["error"] == "capture_requires_one_registered_meeting"
            assert "No hay reuniones registradas" in caplog.text
            assert "Registradas=0, compatibles=0" in caplog.text
            assert "Primero agendá una cita" in caplog.text
            assert other.store.list("transcript") == []
            # A real registration arrives later; the queued capture survives and
            # is correlated on its next retry, without creating a meeting itself.
            case = other.register_meeting(
                {"calendar_id": "primary", "calendar_event_id": "event-one"}, 42
            )["case_id"]
            assert other.run_once()
            monkeypatch.setattr(
                other.store, "clock", lambda: timestamp("2026-11-09T17:00:31Z")
            )
            assert other.run_once()
            assert other.store.job(result.json()["task_id"])["status"] == "done"
            saved = other.store.get(f"transcript:{case}")
            assert saved["segments"] == capture()["segments"]
            assert saved["completion_evidence"] == "browser_capture_ended"
            assert other.process.get(case)["state"]["status"] == "preparing"
            assert len(other.store.list("transcript")) == 1
            assert receive_capture(other, capture())["status"] == "duplicate"
            drafter.assert_not_called()
            google.transcript.assert_not_called()
            # Receipt queued preparation automatically, without an API key or a chat command.
            queued_work = other.open_preparation(case)
            assert queued_work["status"] == "queued"
            auto_task = queued_work["tasks"][0]["id"]
            other.recover_transcript_preparations()
            assert other.open_preparation(case) == queued_work
            # The existing CLI/service journey without notes reuses that same identity.
            text = saved["text"]
            # The active inmobiliaria case was created by the previous interactive
            # flow: a transcript checkpoint paused for chat, with no pending job.
            initial_task = auto_task
            other.store.finish_job(initial_task, status="done")
            with open_checkpointer(other.settings.checkpoint_url) as saver:
                interactive = PreparationService(
                    LangGraphExecution(build_graph(saver, store=other.store)),
                    other.store,
                    other.settings.manager_id,
                )
                paused = interactive.start(
                    case, "capture:" + capture()["capture_id"], text, text
                )
                assert paused["pending"][0]["action"] == "draft_with_chatgpt"
                original_hash = paused["state"]["input_hash"]
            assert other.open_preparation(case)["status"] == "paused"
            drafter.assert_not_called()
            other.recover_transcript_preparations()
            recovered = other.open_preparation(case)
            assert recovered["status"] == "queued"
            auto_task = recovered["tasks"][0]["id"]
            assert other.store.job(auto_task)["payload"]["operation"] == "continue"
            other.recover_transcript_preparations()
            assert other.open_preparation(case) == recovered
            transcript_path = tmp_path / "transcript.txt"
            transcript_path.write_text(text, encoding="utf-8")
            drafter.side_effect = None
            package = ProcessedMeeting(
                title="Aplicación para ventas",
                summary="Aplicación para ventas en cuatro sucursales.",
                objective="Gestionar las ventas.",
                scope="Aplicación para ventas.",
                needs=["Una aplicación para ventas."],
                requirements=["Cuatro sucursales."],
                integrations=[],
                restrictions=[],
                budget="El presupuesto está por confirmar.",
                timeline="La transcripción no establece un plazo.",
                risks=[],
                decisions=[],
                presentation=[
                    {
                        "title": "Aplicación para ventas",
                        "bullets": [
                            "Una aplicación para ventas.",
                            "Cuatro sucursales.",
                        ],
                    }
                ],
            )
            private_json(
                tmp_path / "registration.json",
                {
                    "client_id": "offline",
                    "subject": "offline",
                    "ext_agent_host_id": "offline",
                },
            )
            private_json(
                tmp_path / "session.json",
                {
                    "client_id": "offline",
                    "subject": "offline",
                    "host_id": "offline",
                    "access_token": "offline-oauth",
                    "expires_at": 9999999999,
                },
            )
            inference_requests = []

            def subscription_response(request):
                assert request.headers["authorization"] == "Bearer offline-oauth"
                if request.url.path.endswith("/models"):
                    return httpx.Response(
                        200,
                        json={"models": [{"slug": "offline", "visibility": "list"}]},
                    )
                inference_requests.append(request)
                body = json.loads(request.content)
                assert text in json.loads(body["input"][0]["content"])["transcript"]
                assert "OLD-CATALOG" not in request.content.decode()
                assert body["store"] is False and body["stream"] is True
                assert "max_output_tokens" not in body and "background" not in body
                assert other.open_preparation(case)["status"] == "processing"
                events = [
                    {
                        "type": "response.output_text.delta",
                        "delta": package.model_dump_json(),
                        "output_index": 0,
                        "content_index": 0,
                    },
                    {
                        "type": "response.completed",
                        "response": {
                            "id": "resp_preparation",
                            "status": "completed",
                            "output": [],
                        },
                    },
                ]
                return httpx.Response(
                    200,
                    headers={"content-type": "text/event-stream"},
                    text="\n\n".join("data: " + json.dumps(e) for e in events) + "\n\n",
                )

            with httpx.Client(
                transport=httpx.MockTransport(subscription_response)
            ) as client:
                session = PlanSession(
                    client, tmp_path, "http://localhost/auth/callback"
                )
                drafter.side_effect = ChatGPTPreparer(
                    session,
                    "offline",
                    other.store,
                    allow_inference=False,
                )
                assert (
                    other.run_once()
                )  # Disabled inference never spends the subscription.
                assert other.open_preparation(case)["status"] == "blocked"
                assert inference_requests == []
                server = create_server(other.service, other)
                protected = BearerProtectedMCP(
                    server.streamable_http_app(
                        host="127.0.0.1",
                        stateless_http=True,
                        json_response=True,
                    ),
                    KEY,
                )
                with TestClient(protected, base_url="http://127.0.0.1:8769") as mcp:
                    rpc = {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {
                            "name": "prepare",
                            "arguments": {"proyecto_id": case},
                        },
                    }
                    assert mcp.post("/mcp", json=rpc).status_code == 401
                    headers = {
                        "Authorization": f"Bearer {KEY}",
                        "Accept": "application/json, text/event-stream",
                    }
                    response = mcp.post("/mcp", json=rpc, headers=headers)
                    assert response.status_code == 200
                    assert (
                        json.loads(response.json()["result"]["content"][0]["text"])[
                            "status"
                        ]
                        == "blocked"
                    )
                    # Operator activation belongs to worker configuration, never /prepare.
                    drafter.side_effect.allow_inference = True
                    other.store.retry_job(auto_task)
                    assert other.run_once()
                    response = mcp.post("/mcp", json=rpc, headers=headers)
                    review = json.loads(response.json()["result"]["content"][0]["text"])
                    assert review["status"] == "awaiting_review"
                    assert {f["name"] for f in review["documents"]} == {
                        "resumen-reunion.pdf",
                        "ficha-proyecto.pdf",
                        "presentacion.html",
                        "presentacion.pdf",
                        "transcripcion.pdf",
                    }
                    from pypdf import PdfReader

                    transcript_file = next(
                        f["path"]
                        for f in review["documents"]
                        if f["name"] == "transcripcion.pdf"
                    )
                    transcript_pdf = " ".join(
                        p.extract_text() for p in PdfReader(transcript_file).pages
                    )
                    assert " ".join(text.split()) in " ".join(transcript_pdf.split())
                    assert other.open_preparation(case)["revision"] == 1
                    assert (
                        other.service.get(case)["state"]["input_hash"] == original_hash
                    )
                    assert (
                        other.service.get(case)["pending"][0]["action"]
                        == "manager_review"
                    )
                    other.recover_transcript_preparations()
                    assert "tasks" not in other.open_preparation(case)
                    # Regeneration from a former draft must not feed catalog text
                    # back to the model or reuse its immutable previous artifact.
                    prior = other.service.update_package(
                        case,
                        1,
                        {
                            "summary": package.summary
                            + " OLD-CATALOG: comparación descartada.",
                        },
                    )
                    revision = prior["state"]["revision"]
                    replacement = other.submit_preparation(
                        case,
                        "review",
                        revision=revision,
                        decision="revise",
                        feedback="Regenerar solo desde la transcripción y las notas, sin comparar proyectos.",
                    )
                    assert other.run_once(replacement["task_id"])
                    assert other.store.job(replacement["task_id"])["status"] == "done"
                    regenerated = other.open_preparation(case)
                    assert regenerated["status"] == "awaiting_review"
                    assert regenerated["revision"] == revision + 1
                    assert (
                        "OLD-CATALOG"
                        not in other.service.get(case)["state"]["package"]["summary"]
                    )
                    assert (
                        "OLD-CATALOG"
                        in other.store.get(f"artifact:{case}:{revision}")["documents"][
                            "executive-summary.md"
                        ]
                    )
                assert len(inference_requests) == 2
                drafter.reset_mock()
                drafter.side_effect = None
                drafter.return_value = package
            monkeypatch.setenv("WORKFLOW_ENABLED", "1")
            monkeypatch.setattr(
                workflow_cli,
                "create_runtime",
                lambda *_args, **_kwargs: create_runtime(
                    runtime.settings,
                    google=google,
                    drafter=drafter,
                    clock=runtime.store.clock,
                ),
            )
            workflow_cli.main(
                [
                    "preparation-start",
                    "--case",
                    case,
                    "--event",
                    "capture:" + capture()["capture_id"],
                    "--transcript",
                    str(transcript_path),
                    "--query",
                    text,
                ]
            )
            queued = json.loads(capsys.readouterr().out)
            assert queued["status"] == "done"
            assert queued["task_id"] == initial_task
            drafter.assert_not_called()
            assert other.store.job(queued["task_id"])["status"] == "done"
            prepared = other.service.get(case)["state"]
            assert prepared["meeting_notes"] == ""
            assert (
                prepared["input_hash"]
                == hashlib.sha256(json.dumps([text, text]).encode()).hexdigest()
            )
            asyncio.run(
                create_server(other.service).call_tool(
                    "iniciar_preparacion",
                    {
                        "expediente_id": case,
                        "evento_id": "capture:" + capture()["capture_id"],
                        "transcripcion": text,
                        "consulta": text,
                    },
                )
            )
            assert other.service.continue_preparation(case)["state"] == prepared
            assert drafter.call_count == 0
            notes_path = tmp_path / "meeting-notes.txt"
            notes_path.write_text(
                "Revisar el presupuesto con Stuart.", encoding="utf-8"
            )
            workflow_cli.main(
                [
                    "preparation-start",
                    "--case",
                    case,
                    "--event",
                    "capture:" + capture()["capture_id"],
                    "--transcript",
                    str(transcript_path),
                    "--query",
                    text,
                    "--meeting-notes",
                    str(notes_path),
                ]
            )
            changed = json.loads(capsys.readouterr().out)
            assert changed["task_id"] != queued["task_id"]
            job = other.store.job(changed["task_id"])
            assert (
                job["payload"]["arguments"]["meeting_notes"] == notes_path.read_text()
            )
            with pytest.raises(ValueError, match="otra entrada"):
                other._preparation_command(job["payload"])
            assert other.service.get(case)["state"] == prepared
            republished = other.service.update_package(
                case, prepared["revision"], {"title": package.title}, republish=True
            )["state"]
            assert republished["revision"] == prepared["revision"] + 1
            assert republished["transcript"] == text
            assert republished["input_hash"] == original_hash
            drafter.assert_not_called()
            prepared = republished
            approved = other.service.review(
                case,
                prepared["revision"],
                "approve",
                "Cinco archivos corporativos revisados.",
            )
            assert approved["state"]["status"] == "ready_for_stage_2"
            assert approved["state"]["revision"] == prepared["revision"]
            assert set(
                p.name for p in (runtime.settings.documents_dir / case).iterdir()
            ) == {
                "resumen-reunion.pdf",
                "ficha-proyecto.pdf",
                "presentacion.html",
                "presentacion.pdf",
                "transcripcion.pdf",
            }
            # The approved corporate bytes flow into agent 2 through the same
            # persisted manifest; no speaker-notes step or inferred approval.
            from app.integrations.opening_documents import OpeningDocuments
            from app.persistence.project_opening import ProjectOpeningRepository
            from app.project_opening.conversation import OpeningConversation
            from app.project_opening.service import OpeningService

            manifest = other.store.get(f"artifact-files:{case}:{prepared['revision']}")
            documents = OpeningDocuments(
                runtime.settings.documents_dir / case,
                tmp_path / "unused-template.md",
                other.store,
            )
            repository = ProjectOpeningRepository(other.store)
            opening = OpeningService(repository, Mock(), documents.validate, Mock())
            opening.run = Mock(side_effect=repository.get)
            with open_checkpointer(other.settings.checkpoint_url) as saver:
                conversation = OpeningConversation(opening, saver)
                response = conversation.start()
                session_id = response["session_id"]
                for answer in (case, "sí", "1", "1000", "architect"):
                    response = conversation.respond(session_id, answer)
                assert response["summary"]["files_to_publish"] == 5
                response = conversation.respond(session_id, "sí")
                assert response["files"] == manifest["files"]
                assert (
                    response["incoming_preparation"]["revision"] == prepared["revision"]
                )
            for file in manifest["files"]:
                assert (
                    hashlib.sha256(
                        documents.read(ApprovedFile.model_validate(file), manifest)
                    ).hexdigest()
                    == file["sha256"]
                )
        finally:
            other.close()
    finally:
        app.dependency_overrides.clear()
