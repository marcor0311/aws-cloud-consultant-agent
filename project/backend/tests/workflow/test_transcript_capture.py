"""Browser caption ingestion uses actual HTTP, SQL, queue and LangGraph; no cloud."""

import uuid
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_runtime
from app.bootstrap import create_runtime
from app.main import app
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
    case = runtime.register_meeting(
        {"calendar_id": "primary", "calendar_event_id": "event-one"}, 42
    )["case_id"]
    assert runtime.run_once()
    try:
        yield runtime, case, google, drafter
    finally:
        runtime.close()


def test_authenticated_api_queues_then_worker_preserves_speakers_after_restart(
    ready, monkeypatch
):
    runtime, case, google, drafter = ready
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
            assert runtime.store.get(f"transcript:{case}") is None
        other = create_runtime(
            runtime.settings, google=google, drafter=drafter, clock=runtime.store.clock
        )
        try:
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
        finally:
            other.close()
    finally:
        app.dependency_overrides.clear()


def test_id_reuse_with_changed_content_cannot_overwrite(ready):
    runtime, case, _, _ = ready
    receive_capture(runtime, capture())
    with pytest.raises(ValueError):
        receive_capture(runtime, capture(reporter_name="Another name"))
    runtime.run_once()
    second = receive_capture(runtime, capture(capture_id=str(uuid.uuid4())))
    runtime.run_once()
    assert (
        runtime.store.job(second["task_id"])["error"]
        == "transcript_requires_reconciliation"
    )
    assert (
        runtime.store.get(f"transcript:{case}")["capture_id"] == capture()["capture_id"]
    )


def test_current_meet_room_path_is_accepted_and_correlated(ready):
    runtime, _, _, _ = ready
    body = capture(meeting_url="https://meet.google.com/meet/abc-defg-hij")
    received = receive_capture(runtime, body)
    assert received["status"] == "accepted"
    assert runtime.store.job(received["task_id"])["payload"]["meet_code"] == "abc-defg-hij"


@pytest.mark.parametrize(
    "changes",
    [
        {"meeting_url": "https://attacker.example/abc-defg-hij"},
        {"meeting_url": "https://meet.google.com/abc-defg-hij?redirect=elsewhere"},
        {"capture_id": "not-an-id"},
        {"segments": []},
        {"ended_at": "2026-11-09T15:00:00Z"},
        {
            "segments": [
                {
                    "speaker": "Ana",
                    "at": "2026-11-09T18:00:00Z",
                    "text": "Fuera de intervalo",
                }
            ]
        },
    ],
)
def test_invalid_captures_are_rejected(ready, changes):
    with pytest.raises(ValueError):
        receive_capture(ready[0], capture(**changes))


def test_unknown_or_cancelled_meeting_never_advances_another_project(ready):
    runtime, case, _, _ = ready
    body = capture(meeting_url="https://meet.google.com/xyz-abcd-efg")
    task = receive_capture(runtime, body)["task_id"]
    runtime.run_once()
    assert runtime.store.job(task)["status"] == "pending"
    meeting = runtime.store.get(f"meeting:{case}")
    runtime.store.put(f"meeting:{case}", "meeting", {**meeting, "status": "cancelled"})
    task = receive_capture(runtime, capture(capture_id=str(uuid.uuid4())))["task_id"]
    runtime.run_once()
    assert runtime.store.job(task)["status"] == "pending"
    assert runtime.store.list("transcript") == []
    assert runtime.process.get(case)["state"]["status"] == "awaiting_meeting"
