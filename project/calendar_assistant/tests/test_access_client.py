import json
from unittest.mock import Mock

import pytest

from src import calendar_mcp as calendar
from src.access_client import AccessClient

EMAIL = "persona@example.com"


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
