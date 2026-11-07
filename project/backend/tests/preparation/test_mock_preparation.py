"""Offline acceptance tests for autonomous preparation and Stuart's collaboration."""

import asyncio
import json
import sqlite3

import pytest

from app.bootstrap import create_runtime
from app.demos.workflow import drain, finish_meeting
from app.integrations.mocks import load_projects
from app.mcp_server import create_server
from app.workflow.settings import WorkflowSettings


@pytest.fixture
def mock_runtime(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("An external provider was instantiated in mock mode")

    for name in ("GoogleWorkspace", "OpenAIPreparer", "SlackNotifier"):
        monkeypatch.setattr(f"app.bootstrap.{name}", forbidden)
    runtime = create_runtime(
        WorkflowSettings(
            database_url=f"sqlite:///{tmp_path}/workflow.sqlite3",
            checkpoint_url=str(tmp_path / "checkpoints.sqlite3"),
            mode="mock",
            mock_dir=tmp_path,
            manager_id="stuart",
            pubsub_topic="projects/mock/topics/meet",
        )
    )
    try:
        yield runtime
    finally:
        runtime.close()


def prepare_projects(runtime):
    fixtures = load_projects()
    file = runtime.settings.mock_dir / "mock-calendar.sqlite3"
    with sqlite3.connect(file) as db:
        db.execute(
            "CREATE TABLE mock_calendar_events (id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
        )
        for index, project in enumerate(fixtures):
            event = {
                "id": f"mock-event-{index}",
                "status": "confirmed",
                "summary": project["title"],
                "extendedProperties": {"private": {"calendar_assistant": "stuart"}},
                "conferenceData": {"conferenceId": f"mock-room-{index}"},
                "start": {"dateTime": project["meeting_start"]},
                "end": {"dateTime": project["meeting_start"]},
            }
            db.execute(
                "INSERT INTO mock_calendar_events VALUES (?,?)",
                (event["id"], json.dumps(event)),
            )
    cases = []
    for index, project in enumerate(fixtures):
        case = runtime.register_meeting(
            {
                "calendar_id": "primary",
                "calendar_event_id": f"mock-event-{index}",
                "operation": "scheduled",
                "version": "v1",
            },
            index + 1,
        )["case_id"]
        runtime.store.register_project(
            case,
            project["project_id"],
            project["title"],
            project["company"],
            "stuart",
            is_fictitious=True,
        )
        runtime.store.create_handoff(
            f"{case}:calendar:meeting",
            case,
            "calendar-assistant",
            "stuart",
            "scheduling",
            "initial_meeting",
        )
        cases.append(case)
    drain(runtime)
    assert not runtime.store.list("artifact")
    assert not runtime.store.list("mock_slack")
    for case, project in zip(cases, fixtures, strict=True):
        finish_meeting(runtime, case, project)
    return cases


def test_autonomous_mock_work_is_done_before_stuart_arrives(mock_runtime):
    cases = prepare_projects(mock_runtime)
    notices = mock_runtime.store.list("mock_slack")
    assert len(notices) == 2
    for case in cases:
        state = mock_runtime.service.get(case)
        assert state["state"]["status"] == "awaiting_review"
        assert state["pending"][0]["action"] == "manager_review"
        artifact = mock_runtime.store.get(f"artifact:{case}:1")
        assert set(artifact["documents"]) == {
            "meeting-transcript.md",
            "executive-summary.md",
            "presentation.md",
            "speaker-notes.md",
        }
        assert (
            "No participa ningún agente"
            in artifact["documents"]["meeting-transcript.md"]
        )
        notice = next(n for n in notices if n["case_id"] == case)
        assert "ya preparé" in notice["text"] and notice["is_mock"]
        assert not mock_runtime.store.get(f"handoff:{case}")
        handoff = mock_runtime.store.handoff(f"{case}:preparation:stuart:v1")
        assert handoff["created_at"] <= notice["sent_at"]
        assert handoff["accepted_at"] is None
        prep = next(
            p
            for p in mock_runtime.service.metrics(case)["phases"]
            if p["phase"] == "preparation"
        )
        assert prep["recorded_effort_seconds"]["agent"] == 5
        assert prep["recorded_effort_seconds"]["human"] == 0


def test_langgraph_waits_for_the_human_meeting_and_cancellation_prevents_preparation(
    mock_runtime,
):
    state = mock_runtime.service.wait_for_meeting("waiting-case", "calendar-event")
    assert state["state"]["status"] == "awaiting_meeting"
    assert state["pending"][0]["action"] == "await_meeting_transcript"
    assert (
        mock_runtime.service.continue_preparation("waiting-case")["state"]["status"]
        == "awaiting_meeting"
    )
    assert not mock_runtime.store.list("artifact")
    mock_runtime.service.cancel_waiting_meeting("waiting-case")
    assert (
        mock_runtime.service.get("waiting-case")["state"]["status"]
        == "meeting_cancelled"
    )
    with pytest.raises(ValueError, match="cancelada"):
        mock_runtime.service.start(
            "waiting-case", "event", load_projects()[0]["transcript"], "tienda"
        )
    assert not mock_runtime.store.list("artifact")
    assert not mock_runtime.store.list("phase")


def test_mcp_selects_project_and_reading_does_not_accept_or_approve(mock_runtime):
    cases = prepare_projects(mock_runtime)
    server = create_server(mock_runtime.service, mock_runtime)

    async def exercise():
        listing = await server.call_tool("agente_preparacion", {})
        data = json.loads(listing.content[0].text)
        assert data["status"] == "project_selection_required"
        assert len(data["projects"]) == 2
        selected = await server.call_tool(
            "agente_preparacion", {"proyecto_id": "reservas-sierra-aventura"}
        )
        project = json.loads(selected.content[0].text)
        assert project["project"]["case_id"] == cases[1]
        assert project["package"]["budget"]["status"] == "confirmed"
        assert "12 000" in project["package"]["budget"]["text"]
        assert (
            "Tienda Deportiva Horizonte"
            not in project["documents"]["meeting-transcript.md"]
        )

    asyncio.run(exercise())
    for case in cases:
        assert (
            mock_runtime.store.handoff(f"{case}:preparation:stuart:v1")["accepted_at"]
            is None
        )
        assert mock_runtime.service.get(case)["state"]["revision"] == 1


def test_collaboration_is_versioned_persistent_and_requires_exact_approval(
    mock_runtime,
):
    first, other = prepare_projects(mock_runtime)
    clock = mock_runtime.mock_clock
    clock.advance(600)
    mock_runtime.service.begin_review(first, 1)
    clock.advance(45)
    before = mock_runtime.service.get(first)["state"]["package"]
    changed = mock_runtime.service.update_package(
        first,
        1,
        {"summary": "Priorizar el MVP. " + before["summary"]},
        "Cambio discutido con Stuart",
    )
    assert changed["state"]["revision"] == 2
    assert changed["state"]["status"] == "awaiting_review"
    assert (
        mock_runtime.store.get(f"artifact:{first}:1")["package"]["summary"]
        == before["summary"]
    )
    assert mock_runtime.store.case_notes(first)[0]["actor"] == "stuart"
    with pytest.raises(ValueError, match="revisión cambió"):
        mock_runtime.service.review(first, 1, "approve")
    clock.advance(15)
    mock_runtime.service.begin_review(first, 2)
    mock_runtime.service.review(first, 2, "approve")
    transfer = f"{first}:stage-1:stage-2:v2"
    with pytest.raises(ValueError, match="asignada"):
        mock_runtime.store.accept_handoff(transfer, "stuart")
    clock.advance(120)
    mock_runtime.store.accept_handoff(transfer, "executive-direction-agent")
    assert (
        mock_runtime.store.get(f"handoff:{first}")["receipt"] == "accepted_by_stage_2"
    )
    metrics = mock_runtime.service.metrics(first)
    assert metrics["stage_1"]["completed_at"] is not None
    prep = next(p for p in metrics["phases"] if p["phase"] == "preparation")
    assert prep["recorded_effort_seconds"]["human"] == 60
    assert prep["open_sessions"] == 0
    assert mock_runtime.service.get(other)["state"]["status"] == "awaiting_review"


def test_invalid_edits_leave_checkpoint_and_artifacts_untouched(mock_runtime):
    case = prepare_projects(mock_runtime)[0]
    before = mock_runtime.service.get(case)
    with pytest.raises(ValueError):
        mock_runtime.service.update_package(
            case,
            1,
            {
                "budget": {
                    "text": "Presupuesto de un millón aprobado",
                    "status": "confirmed",
                    "citations": [],
                }
            },
        )
    assert mock_runtime.service.get(case) == before
    assert mock_runtime.store.get(f"artifact:{case}:2") is None


def test_mock_data_survives_restart_without_resending_notices(mock_runtime):
    case = prepare_projects(mock_runtime)[0]
    settings = mock_runtime.settings
    mock_runtime.service.update_package(
        case, 1, {"speaker_notes": "Guion mejorado y guardado por Stuart."}
    )
    mock_runtime.close()
    restarted = create_runtime(settings)
    try:
        opened = restarted.open_preparation("tienda-deportiva-horizonte")
        assert opened["revision"] == 2
        assert "Guion mejorado" in opened["documents"]["speaker-notes.md"]
        assert opened["status"] == "awaiting_review"
        drain(restarted)
        count = len(restarted.store.list("mock_slack"))
        drain(restarted)
        assert len(restarted.store.list("mock_slack")) == count
    finally:
        restarted.close()
