import json
from datetime import datetime
from io import BytesIO
from unittest.mock import Mock

import pytest

from src import access_client
from src import calendar_mcp as calendar
from src.access_client import AccessClient

EMAIL = "persona@example.com"


@pytest.fixture
def authorization_transport(monkeypatch):
    """Mock only the HTTP boundary, keeping the real _request argument binding."""
    monkeypatch.setenv(
        "CALENDAR_ACCESS_URL", "http://127.0.0.1:8990/api/calendar-access"
    )
    monkeypatch.setenv(
        "CALENDAR_ACCESS_SERVICE_KEY", "test-service-key-abcdefghijklmnopqrstuvwxyz"
    )
    requests = []

    def open_request(request, **kwargs):
        requests.append(request)
        return BytesIO(json.dumps({"status": "authorized", "email": EMAIL}).encode())

    monkeypatch.setattr(
        access_client, "build_opener", lambda *_: Mock(open=open_request)
    )
    return requests


@pytest.mark.parametrize(
    "operation", ["availability", "search", "book", "reschedule", "cancel"]
)
def test_authorization_posts_operation_in_json_without_colliding_with_endpoint(
    authorization_transport, operation
):
    client = AccessClient()
    client.email = EMAIL
    client.require(operation, EMAIL)
    request = authorization_transport[0]
    assert request.full_url == "http://127.0.0.1:8990/api/calendar-access/authorize"
    assert json.loads(request.data) == {
        "session_id": client.session_id,
        "email": EMAIL,
        "operation": operation,
    }


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"fecha_solicitada": "mañana"},
        {"fecha_solicitada": "mañana", "hora_solicitada": "08:30"},
    ],
)
def test_availability_reaches_calendar_after_real_authorization_request(
    monkeypatch, authorization_transport, arguments
):
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            fixed = cls(2026, 11, 3, 7, tzinfo=calendar.TIME_ZONE)
            return fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None)

    client = AccessClient()
    client.email = EMAIL
    monkeypatch.setattr(calendar, "_access", client)
    monkeypatch.setattr(calendar, "datetime", FrozenDatetime)
    google = Mock()
    google.freebusy.return_value.query.return_value.execute.return_value = {
        "calendars": {"primary": {"busy": []}}
    }
    monkeypatch.setattr(calendar, "_calendar_service", lambda: google)
    result = calendar.consultar_horarios(correo_confirmado=EMAIL, **arguments)
    assert result["dias_disponibles"]
    assert json.loads(authorization_transport[0].data)["operation"] == "availability"
    if arguments.get("hora_solicitada"):
        assert result["horario_solicitado"]["inicio"] == "2026-11-04T08:30-06:00"
    google.freebusy.return_value.query.assert_called_once()


def test_call_identity_and_challenge_are_never_exposed_to_model(monkeypatch):
    client = AccessClient()
    assert client.session_id != AccessClient().session_id
    request = Mock(
        return_value={
            "status": "code_sent",
            "challenge_id": "private-challenge-123456789",
            "expires_in_seconds": 300,
        }
    )
    monkeypatch.setattr(client, "_request", request)
    result = client.start(EMAIL)
    assert result == {"estado": "code_sent", "expires_in_seconds": 300}
    assert "private-challenge" not in json.dumps(result)
    assert client.session_id not in json.dumps(result)
    assert request.call_args.kwargs["email"] == EMAIL


def test_verification_preserves_zeroes_and_checks_backend_email(monkeypatch):
    client = AccessClient()
    client.email, client.challenge_id = EMAIL, "private-challenge-123456789"
    request = Mock(return_value={"status": "verified", "email": EMAIL})
    monkeypatch.setattr(client, "_request", request)
    assert client.verify("0, 0, 3, 1, 2, 0")["estado"] == "verified"
    assert request.call_args.kwargs["code"] == "003120"
    request.return_value = {"status": "verified", "email": "other@example.com"}
    assert client.verify("003120")["estado"] == "unavailable"


def test_client_only_authorizes_matching_verified_email(monkeypatch):
    client = AccessClient()
    client.email = EMAIL
    request = Mock(return_value={"status": "verification_required"})
    monkeypatch.setattr(client, "_request", request)
    with pytest.raises(ValueError):
        client.require("book", EMAIL)
    request.return_value = {"status": "authorized", "email": EMAIL}
    client.require("book", EMAIL)
    client.require("availability")
    with pytest.raises(ValueError):
        client.require("cancel", "other@example.com")
    request.return_value = {"status": "unavailable"}
    with pytest.raises(RuntimeError):
        client.require("book", EMAIL)


def test_unconfigured_backend_fails_closed(monkeypatch):
    monkeypatch.delenv("CALENDAR_ACCESS_SERVICE_KEY", raising=False)
    assert AccessClient().start(EMAIL)["estado"] == "unavailable"


@pytest.mark.parametrize(
    "name,args",
    [
        ("consultar_horarios", {}),
        ("buscar_reuniones", {"correo_confirmado": EMAIL}),
        (
            "agendar_reunion",
            {
                "inicio": "2026-11-04T10:00:00-06:00",
                "nombre": "Persona",
                "correo_confirmado": EMAIL,
            },
        ),
        (
            "reagendar_reunion",
            {
                "evento_id": "id",
                "nuevo_inicio": "2026-11-04T10:00:00-06:00",
                "correo_confirmado": EMAIL,
                "inicio_original_confirmado": "2026-11-03T10:00:00-06:00",
                "confirmacion_usuario": True,
            },
        ),
        (
            "cancelar_reunion",
            {
                "evento_id": "id",
                "correo_confirmado": EMAIL,
                "inicio_original_confirmado": "2026-11-03T10:00:00-06:00",
                "confirmacion_usuario": True,
            },
        ),
    ],
)
def test_every_calendar_tool_is_blocked_before_google_access(monkeypatch, name, args):
    client = AccessClient()
    monkeypatch.setattr(calendar, "_access", client)
    google = Mock(side_effect=AssertionError("Google must not be called"))
    monkeypatch.setattr(calendar, "_calendar_service", google)
    with pytest.raises(ValueError, match="verifica"):
        getattr(calendar, name)(**args)
    google.assert_not_called()


def test_mcp_tools_delegate_without_accepting_caller_chosen_session(monkeypatch):
    client = Mock()
    monkeypatch.setattr(calendar, "_access", client)
    calendar.iniciar_verificacion_correo("persona@example.com")
    client.start.assert_called_once_with(EMAIL)
    calendar.validar_codigo_correo("003120")
    client.verify.assert_called_once_with("003120")
    calendar.reenviar_codigo_correo()
    client.resend.assert_called_once_with()
