"""The public ingress shares the callback without exposing private API routes."""

from unittest.mock import Mock

from fastapi.testclient import TestClient

from app.api.dependencies import get_runtime
from app.calendar_webhook import app
from app.workflow.calendar_sync import CalendarSync


def test_public_entry_exposes_only_calendar_callback(monkeypatch):
    runtime = Mock()
    receiver = Mock(return_value={"status": "accepted"})
    monkeypatch.setattr(CalendarSync, "receive", receiver)
    app.dependency_overrides[get_runtime] = lambda: runtime
    try:
        with TestClient(app) as api:
            for path in (
                "/",
                "/docs",
                "/redoc",
                "/openapi.json",
                "/api/workflow/cases",
                "/api/calendar-access/start",
                "/api/calendar-access/call-ended",
                "/api/workflow/events/transcript",
            ):
                assert api.get(path).status_code == 404
                assert api.post(path).status_code == 404
            assert api.post("/api/workflow/events/calendar/").status_code == 404
            assert api.get("/api/workflow/events/calendar").status_code == 405
            receiver.assert_not_called()
            result = api.post(
                "/api/workflow/events/calendar",
                headers={"x-goog-channel-id": "test-channel"},
            )
            assert result.status_code == 202
            receiver.assert_called_once()
            assert receiver.call_args.args[0]["x-goog-channel-id"] == "test-channel"
    finally:
        app.dependency_overrides.clear()


def test_public_entry_keeps_webhook_validation():
    runtime = Mock()
    runtime.store.get.return_value = None
    app.dependency_overrides[get_runtime] = lambda: runtime
    try:
        with TestClient(app) as api:
            assert api.post("/api/workflow/events/calendar").status_code == 403
            runtime.store.receive.assert_not_called()
    finally:
        app.dependency_overrides.clear()
