"""Exercise the assembled API with real temporary storage and a fake email boundary."""

from fastapi.testclient import TestClient

from app.api.dependencies import get_access_service
from app.clients.repository import ClientRepository
from app.main import app
from app.notifications.provider import EnvironmentMailer


def test_composed_api_verifies_only_after_email_otp(tmp_path, monkeypatch):
    database = tmp_path / "clients.sqlite3"
    client = ClientRepository(database).create(
        "Empresa de prueba", "approved@example.test"
    )
    key = "synthetic-service-key-12345678901234567890"
    monkeypatch.setenv("CALENDAR_ACCESS_DB", str(database))
    monkeypatch.setenv("CALENDAR_ACCESS_SERVICE_KEY", key)
    monkeypatch.setenv(
        "CALENDAR_ACCESS_CODE_SECRET", "synthetic-otp-secret-12345678901234567890"
    )
    messages = []
    monkeypatch.setattr(
        EnvironmentMailer, "send_code", lambda self, *args: messages.append(args)
    )
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
            response = api.post(
                "/api/calendar-access/start",
                headers=headers,
                json={
                    "session_id": session,
                    "client_code": client.client_code,
                    "origin_id": "test",
                },
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
