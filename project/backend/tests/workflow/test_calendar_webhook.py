"""Post-call receipts and Calendar notifications, with real SQL/graphs and no providers."""

import hashlib
import hmac
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_access_service, get_runtime
from app.bootstrap import create_runtime
from app.integrations.errors import ProviderError
from app.main import app
from app.workflow.calendar_sync import CalendarSync
from app.workflow.receipts import accept_call_receipt
from app.workflow.settings import WorkflowSettings

KEY = "offline-only-service-key-12345678901234567890"


@pytest.fixture
def tracking(tmp_path):
    client = SimpleNamespace(
        client_id=42,
        client_code="DEMO-0001",
        company_email="client@example.test",
        enabled=True,
    )
    google = Mock()
    google.calendar_event.return_value = {
        "id": "event-1",
        "etag": "v1",
        "summary": "Primera reunión",
        "status": "confirmed",
        "start": {"dateTime": "2026-11-09T10:00:00-06:00"},
        "end": {"dateTime": "2026-11-09T10:30:00-06:00"},
        "attendees": [{"email": client.company_email}],
        "extendedProperties": {
            "private": {
                "calendar_assistant": "stuart",
                "workflow_client_code": client.client_code,
            }
        },
        "conferenceData": {"conferenceId": "abc-defg-hij"},
    }
    settings = WorkflowSettings(
        database_url=f"sqlite:///{tmp_path / 'workflow.sqlite3'}",
        checkpoint_url=str(tmp_path / "checkpoints.sqlite3"),
        enabled=True,
        calendar_webhook_url="https://callback.example.test/api/workflow/events/calendar",
        post_call_dir=tmp_path / "outbox",
    )

    def lookup(code):
        return client if code == client.client_code else None

    runtime = create_runtime(settings, google=google, client_lookup=lookup)
    runtime.drafter = Mock(side_effect=AssertionError("No AI in Calendar tracking"))
    try:
        yield runtime, google, client
    finally:
        runtime.close()


def receipt(**changes):
    body = {
        "call_id": "one-closed-voice-call",
        "client_code": "DEMO-0001",
        "email": "client@example.test",
        "calendar_id": "primary",
        "calendar_event_id": "event-1",
        "operation": "scheduled",
        "version": "v1",
        "started_at": "2026-11-06T10:00:00+00:00",
        "completed_at": "2026-11-06T10:00:02+00:00",
        "closed_at": "2026-11-06T10:03:00+00:00",
        **changes,
    }
    return {
        "body": body,
        "signature": hmac.new(
            KEY.encode(), json.dumps(body, sort_keys=True).encode(), hashlib.sha256
        ).hexdigest(),
    }


def accept(runtime, **changes):
    return accept_call_receipt(runtime, receipt(**changes), KEY, runtime.client_lookup)[
        "case_id"
    ]


def subscribe(runtime, google):
    google.watch_calendar.return_value = {
        "resourceId": "calendar-resource",
        "expiration": str(int((runtime.store.clock() + 604800) * 1000)),
    }
    google.calendar_changes.return_value = {"items": [], "nextSyncToken": "cursor-1"}
    sync = CalendarSync(runtime)
    sync.subscribe()
    assert runtime.run_once()
    channel = runtime.store.list("calendar_channel")[-1]
    return {
        "x-goog-channel-id": channel["id"],
        "x-goog-channel-token": channel["token"],
        "x-goog-resource-id": "calendar-resource",
        "x-goog-resource-state": "exists",
        "x-goog-message-number": "2",
    }


def test_receipt_persists_without_google_and_survives_restart(tracking):
    runtime, google, client = tracking
    case = accept(runtime)
    google.calendar_event.assert_not_called()
    assert len(runtime.store.list("meeting")) == 1
    assert accept(runtime) == case
    other = create_runtime(
        runtime.settings, google=google, client_lookup=runtime.client_lookup
    )
    try:
        assert other.run_once()
        assert other.process.get(case)["state"]["status"] == "awaiting_meeting"
        assert other.store.get(f"meeting:{case}")["client_id"] == client.client_id
        google.space.assert_not_called()
        google.watch_calendar.assert_not_called()
    finally:
        other.close()


def test_post_call_api_accepts_closed_session_receipt_and_rejects_tampering(
    tracking, monkeypatch
):
    runtime, google, client = tracking
    monkeypatch.setenv("CALENDAR_ACCESS_SERVICE_KEY", KEY)
    app.dependency_overrides[get_runtime] = lambda: runtime
    app.dependency_overrides[get_access_service] = lambda: SimpleNamespace(
        clients=SimpleNamespace(lookup_code=runtime.client_lookup)
    )
    try:
        with TestClient(app) as api:
            headers = {"Authorization": f"Bearer {KEY}"}
            assert (
                api.post("/api/calendar-access/call-ended", json=receipt()).status_code
                == 401
            )
            altered = receipt()
            altered["body"]["calendar_event_id"] = "wrong"
            assert (
                api.post(
                    "/api/calendar-access/call-ended", json=altered, headers=headers
                ).status_code
                == 400
            )
            result = api.post(
                "/api/calendar-access/call-ended", json=receipt(), headers=headers
            )
            assert result.status_code == 200
            assert result.json()["status"] == "registered"
            google.calendar_event.assert_not_called()
    finally:
        app.dependency_overrides.clear()


def test_reschedule_then_cancel_webhook_updates_same_project(tracking):
    runtime, google, _ = tracking
    case = accept(runtime)
    runtime.run_once()
    headers = subscribe(runtime, google)
    google.calendar_event.return_value["start"]["dateTime"] = (
        "2026-11-10T14:00:00-06:00"
    )
    google.calendar_event.return_value["end"]["dateTime"] = "2026-11-10T14:30:00-06:00"
    google.calendar_changes.return_value = {
        "items": [{"id": "event-1", "etag": "v2"}],
        "nextSyncToken": "cursor-2",
    }
    app.dependency_overrides[get_runtime] = lambda: runtime
    try:
        with TestClient(app) as api:
            assert (
                api.post(
                    "/api/workflow/events/calendar",
                    headers={**headers, "x-goog-channel-token": "wrong"},
                ).status_code
                == 403
            )
            assert (
                api.post("/api/workflow/events/calendar", headers=headers).json()[
                    "status"
                ]
                == "accepted"
            )
            assert (
                api.post("/api/workflow/events/calendar", headers=headers).json()[
                    "status"
                ]
                == "duplicate"
            )
        assert runtime.run_once() and runtime.run_once()
        assert (
            runtime.store.get(f"meeting:{case}")["start"] == "2026-11-10T14:00:00-06:00"
        )
        assert runtime.process.get(case)["state"]["status"] == "awaiting_meeting"
        google.calendar_changes.assert_called_with("primary", "cursor-1", "")
        google.calendar_changes.return_value = {
            "items": [{"id": "event-1", "status": "cancelled", "etag": "v3"}],
            "nextSyncToken": "cursor-3",
        }
        CalendarSync(runtime).receive({**headers, "x-goog-message-number": "3"})
        assert runtime.run_once() and runtime.run_once()
        assert runtime.store.get(f"meeting:{case}")["status"] == "cancelled"
        assert runtime.process.get(case)["state"]["status"] == "cancelled"
        assert len(runtime.store.list("meeting")) == 1
    finally:
        app.dependency_overrides.clear()


def test_sync_recovers_410_and_ignores_unregistered_events(tracking):
    runtime, google, _ = tracking
    runtime.store.put(
        "calendar-sync:primary", "calendar_sync", {"sync_token": "expired"}
    )
    google.calendar_changes.side_effect = [
        ProviderError("google_http_410"),
        {"items": [{"id": "not-our-meeting"}], "nextSyncToken": "new"},
    ]
    CalendarSync(runtime).sync("primary")
    assert google.calendar_changes.call_args_list[1].args == ("primary", "", "")
    assert runtime.store.list("meeting") == []
    assert runtime.store.get("calendar-sync:primary")["sync_token"] == "new"


def test_worker_retries_ready_receipts_but_never_active_calls(tracking, monkeypatch):
    runtime, _, _ = tracking
    monkeypatch.setenv("CALENDAR_ACCESS_SERVICE_KEY", KEY)
    directory = runtime.settings.post_call_dir
    directory.mkdir()
    (directory / "still-calling.active").write_text(json.dumps(receipt()))
    path = directory / "closed.json"
    path.write_text(json.dumps(receipt()))
    runtime.deliver_post_calls()
    assert not path.exists()
    assert (directory / "still-calling.active").exists()
    assert len(runtime.store.list("meeting")) == 1


def test_maintenance_does_not_poll_calendar_and_watch_is_reused(tracking):
    runtime, google, _ = tracking
    subscribe(runtime, google)
    runtime.maintenance()
    google.watch_calendar.assert_called_once()
    google.calendar_events.assert_not_called()


def test_call_cannot_overwrite_another_final_result(tracking):
    runtime, _, _ = tracking
    accept(runtime)
    with pytest.raises(ValueError, match="otro resultado"):
        accept(runtime, version="different")
