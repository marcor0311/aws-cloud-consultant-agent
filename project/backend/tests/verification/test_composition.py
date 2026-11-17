"""Exercise the assembled API with real temporary storage and a fake email boundary."""

import json
from unittest.mock import Mock

from fastapi.testclient import TestClient
from google.auth.exceptions import RefreshError

from app.api.dependencies import get_access_service
from app.clients.repository import ClientRepository
from app.main import app
from app.notifications.gmail import GMAIL_SEND_SCOPE
from app.notifications.provider import EnvironmentMailer


def test_composed_api_verifies_only_after_email_otp(tmp_path, monkeypatch, caplog):
    database = tmp_path / "clients.sqlite3"
    client = ClientRepository(database).create(
        "Empresa de prueba", "approved@example.test"
    )
    key = "synthetic-service-key-12345678901234567890"  # gitleaks:allow -- offline fixture
    monkeypatch.setenv("CALENDAR_ACCESS_DB", str(database))
    monkeypatch.setenv("CALENDAR_ACCESS_SERVICE_KEY", key)
    monkeypatch.setenv(
        "CALENDAR_ACCESS_CODE_SECRET",
        "synthetic-otp-secret-12345678901234567890",  # gitleaks:allow -- offline fixture
    )
    messages = []
    get_access_service.cache_clear()
    session = "synthetic-call-1234567890"
    headers = {"Authorization": f"Bearer {key}"}
    try:
        with TestClient(app) as api:
            assert api.get("/").status_code == 200
            assert (
                api.post(
                    "/api/calendar-access/close", json={"session_id": session}
                ).status_code
                == 401
            )
            authorization = {
                "session_id": session,
                "email": client.company_email,
                "operation": "book",
            }
            assert (
                api.post(
                    "/api/calendar-access/authorize",
                    headers=headers,
                    json=authorization,
                ).json()["status"]
                == "verification_required"
            )
            start = {
                "session_id": session,
                "client_code": client.client_code,
                "origin_id": "test",
            }
            # A rejected Gmail renewal must be diagnosable without exposing its
            # response or accidentally authorizing the caller after a failed send.
            token = tmp_path / "gmail-token.json"
            token.write_text(
                json.dumps(
                    {
                        "scopes": [GMAIL_SEND_SCOPE],
                        "token_uri": "https://oauth2.googleapis.com/token",
                    }
                )
            )
            credentials = Mock(expired=True, refresh_token="offline-only")
            credentials.refresh.side_effect = RefreshError(
                "private-oauth-response",
                {
                    "error": "invalid_grant",
                    "error_description": "private-oauth-response",
                },
            )
            calendar_token = tmp_path / "calendar-token.json"
            calendar_token.write_text(
                json.dumps(
                    {
                        "scopes": [
                            "https://www.googleapis.com/auth/calendar.events.owned"
                        ],
                        "token_uri": "https://oauth2.googleapis.com/token",
                    }
                )
            )
            calendar_credentials = Mock()
            with monkeypatch.context() as gmail:
                gmail.setenv("CALENDAR_MAIL_PROVIDER", "gmail")
                gmail.setenv("GOOGLE_ACCOUNT_EMAIL", "sender@example.test")
                gmail.setenv("CALENDAR_GMAIL_TOKEN_FILE", str(token))
                gmail.setenv("GOOGLE_OAUTH_TOKEN_FILE", str(calendar_token))
                gmail.setenv("WORKFLOW_ENABLED", "1")
                gmail.setenv("WORKFLOW_GOOGLE_TOKEN_FILE", str(calendar_token))
                gmail.setattr(
                    "app.notifications.gmail.Credentials.from_authorized_user_info",
                    lambda info: (
                        credentials
                        if GMAIL_SEND_SCOPE in info["scopes"]
                        else calendar_credentials
                    ),
                )
                send = Mock(side_effect=AssertionError("No real mail"))
                gmail.setattr("app.notifications.gmail.httpx.post", send)
                # Health diagnoses all configured Google authorizations before
                # OTP issuance, including a shared Calendar/workflow token.
                health = api.get("/health")
                assert health.status_code == 503
                checks = health.json()["checks"]
                assert checks["gmail"]["code"] == "invalid_grant"
                assert "make gmail-auth" in checks["gmail"]["action"]
                assert checks["calendar"]["status"] == "ok"
                assert checks["workflow_google"]["status"] == "ok"
                calendar_credentials.refresh.assert_called_once()
                assert "private-oauth-response" not in health.text
                assert client.company_email not in health.text
                send.assert_not_called()
                failed = api.post(
                    "/api/calendar-access/start", headers=headers, json=start
                )
                assert failed.json()["status"] == "unavailable"
                send.assert_not_called()
                # Browser reauthorization replaces the file. Health notices that
                # change immediately and probes without modifying the new token.
                credentials.refresh.side_effect = None
                renewed = token.read_text() + "\n"
                token.write_text(renewed)
                recovered = api.get("/health")
                assert recovered.status_code == 200
                assert recovered.json()["checks"]["gmail"]["status"] == "ok"
                assert token.read_text() == renewed
                send.assert_not_called()
            assert "gmail_oauth_refresh_rejected" in caplog.text
            assert "invalid_grant" in caplog.text
            assert "make gmail-auth" in caplog.text
            assert "private-oauth-response" not in caplog.text + failed.text
            assert client.company_email not in caplog.text + failed.text
            assert (
                api.post(
                    "/api/calendar-access/authorize",
                    headers=headers,
                    json=authorization,
                ).json()["status"]
                == "verification_required"
            )
            monkeypatch.setattr(
                EnvironmentMailer,
                "send_code",
                lambda self, *args: messages.append(args),
            )
            # Failed sends still consume the existing cooldown; recovery does
            # not bypass its counters or allow verification without a new OTP.
            assert (
                api.post(
                    "/api/calendar-access/start", headers=headers, json=start
                ).json()["status"]
                == "rate_limited"
            )
            service = get_access_service()
            after_cooldown = service.clock() + service.policy.resend_cooldown + 1
            monkeypatch.setattr(service, "clock", lambda: after_cooldown)
            response = api.post(
                "/api/calendar-access/start",
                headers=headers,
                json=start,
            )
            challenge = response.json()
            assert response.status_code == 200 and challenge["status"] == "code_sent"
            assert messages[0][0] == client.company_email
            assert client.company_email not in response.text
            otp = messages[0][2]
            assert otp not in response.text
            verified = api.post(
                "/api/calendar-access/verify",
                headers=headers,
                json={
                    "session_id": session,
                    "challenge_id": challenge["challenge_id"],
                    "code": otp,
                },
            )
            assert verified.json()["status"] == "verified"
            assert (
                api.post(
                    "/api/calendar-access/authorize",
                    headers=headers,
                    json=authorization,
                ).json()["status"]
                == "authorized"
            )
            api.post(
                "/api/calendar-access/close",
                headers=headers,
                json={"session_id": session},
            )
            assert (
                api.post(
                    "/api/calendar-access/authorize",
                    headers=headers,
                    json=authorization,
                ).json()["status"]
                == "verification_required"
            )
    finally:
        get_access_service.cache_clear()
