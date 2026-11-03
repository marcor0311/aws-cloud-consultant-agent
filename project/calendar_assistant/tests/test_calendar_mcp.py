from copy import deepcopy
from datetime import datetime, timedelta
from unittest.mock import Mock

import pytest
from googleapiclient.errors import HttpError
from httplib2 import Response

from src import calendar_mcp as calendar

FIXED_NOW = datetime(2026, 10, 30, 7, tzinfo=calendar.TIME_ZONE)
NEW_START = "2026-11-02T14:00:00-06:00"
EMAIL = "persona031120@gmail.com"


class FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return FIXED_NOW.astimezone(tz) if tz else FIXED_NOW.replace(tzinfo=None)


@pytest.fixture
def calendar_api(monkeypatch):
    # Calendar business-rule tests assume an authenticated caller. Access guards
    # are exercised separately in test_access_client.py without this fixture.
    monkeypatch.setattr(calendar, "_require_access", lambda *_: None)
    monkeypatch.setattr(calendar, "datetime", FrozenDatetime)
    service = Mock()
    events = service.events.return_value
    events.patch.return_value.headers = {}
    events.patch.return_value.execute.return_value = {"id": "stuart-original"}
    events.delete.return_value.headers = {}
    events.delete.return_value.execute.return_value = ""
    monkeypatch.setattr(calendar, "_calendar_service", lambda: service)
    return service, events


def meeting(event_id="stuart-original", start="2026-10-30T10:30:00-06:00"):
    end = datetime.fromisoformat(start) + timedelta(minutes=30)
    return {
        "id": event_id,
        "etag": '"version-1"',
        "summary": "Reunión con Stuart — Futura",
        "description": "Reunión de 30 minutos con Stuart, gerente de Relaciones con el Cliente.",
        "organizer": {"self": True},
        "start": {"dateTime": start},
        "end": {"dateTime": end.isoformat()},
        "attendees": [{"email": EMAIL}, {"email": "otro@example.com"}],
    }


def reschedule(**kwargs):
    args = {
        "evento_id": "stuart-original",
        "nuevo_inicio": NEW_START,
        "correo_confirmado": EMAIL,
        "inicio_original_confirmado": "2026-10-30T10:30:00-06:00",
        "confirmacion_usuario": True,
    }
    args.update(kwargs)
    return calendar.reagendar_reunion(**args)


def cancel(**kwargs):
    args = {
        "evento_id": "stuart-original",
        "correo_confirmado": EMAIL,
        "inicio_original_confirmado": "2026-10-30T10:30:00-06:00",
        "confirmacion_usuario": True,
    }
    args.update(kwargs)
    return calendar.cancelar_reunion(**args)


def test_gmail_domain_is_spoken_normally_but_username_is_spelled():
    result = calendar.preparar_confirmacion_correo("Persona 031120@GMAIL.COM")
    assert result["correo_normalizado"] == EMAIL
    assert "cero, tres, uno, uno, dos, cero" in result["correo_deletreado"]
    assert result["correo_deletreado"].endswith("arroba, gmail punto com")
    assert "ge, eme, a, i, ele" not in result["correo_deletreado"]


@pytest.mark.parametrize("domain", ["futura.com", "gmail.co.cr", "example.org"])
def test_every_other_domain_is_spelled_completely(domain):
    result = calendar.preparar_confirmacion_correo(f"persona@{domain}")
    assert result["correo_deletreado"].endswith(calendar._spell_email(domain))


def test_invalid_email_is_not_presented_as_confirmable():
    result = calendar.preparar_confirmacion_correo("persona sin arroba")
    assert result["estado"] == "invalido"
    assert result["correo_normalizado"] == ""


@pytest.mark.parametrize("google_organizer", [None, "calendar-owner@example.com"])
def test_booking_requires_no_company_and_remains_findable_by_email(
    calendar_api, monkeypatch, google_organizer
):
    service, events = calendar_api
    service.freebusy.return_value.query.return_value.execute.return_value = {
        "calendars": {"primary": {"busy": []}}
    }
    monkeypatch.setenv("GOOGLE_ACCOUNT_EMAIL", "configured-owner@example.com")
    created = {"id": "new-meeting"}
    if google_organizer:
        created["organizer"] = {"email": google_organizer}
    events.insert.return_value.execute.return_value = created
    result = calendar.agendar_reunion(
        inicio=NEW_START, nombre="Persona", correo_confirmado=EMAIL
    )
    assert result["estado"] == "agendada"
    assert result["organizador"] == (google_organizer or "configured-owner@example.com")
    body = events.insert.call_args.kwargs["body"]
    assert body["summary"] == "Reunión con Stuart — Persona"
    assert "Empresa:" not in body["description"]
    assert "empresa" not in body["extendedProperties"]["private"]
    body["organizer"] = {"self": True}
    assert calendar._matches_stuart_meeting(body, EMAIL)


def test_search_filters_by_exact_attendee_and_stuart_event_with_pagination(
    calendar_api,
):
    _, events = calendar_api
    unrelated = meeting("personal")
    unrelated["summary"] = "Otra reunión"
    wrong_attendee = meeting("different-user")
    wrong_attendee["attendees"] = [{"email": "different@example.com"}]
    other_company = meeting("different-company")
    other_company["summary"] = "Reunión con Stuart — Otra empresa"
    events.list.return_value.execute.side_effect = [
        {"items": [unrelated, wrong_attendee, other_company], "nextPageToken": "page2"},
        {"items": [meeting()]},
    ]
    result = calendar.buscar_reuniones(EMAIL)
    assert [item["evento_id"] for item in result["reuniones"]] == [
        "different-company",
        "stuart-original",
    ]
    assert "different@example.com" not in str(result)
    assert events.list.call_args.kwargs["pageToken"] == "page2"
    events.patch.assert_not_called()


def test_no_calendar_access_without_explicit_reschedule_confirmation(calendar_api):
    service, events = calendar_api
    with pytest.raises(ValueError, match="confirmación explícita"):
        reschedule(confirmacion_usuario=False)
    service.events.assert_not_called()
    events.patch.assert_not_called()


def test_cannot_reschedule_a_meeting_where_the_given_email_is_not_an_attendee(
    calendar_api,
):
    _, events = calendar_api
    events.get.return_value.execute.return_value = meeting()
    with pytest.raises(ValueError, match="coincida"):
        reschedule(correo_confirmado="wrong@example.com")
    events.patch.assert_not_called()


def test_reschedule_rejects_past_meetings(calendar_api):
    _, events = calendar_api
    events.get.return_value.execute.return_value = meeting(
        start="2026-10-29T10:30:00-06:00"
    )
    with pytest.raises(ValueError, match="ya comenzó"):
        reschedule()
    events.patch.assert_not_called()


@pytest.mark.parametrize(
    "start",
    [
        "2026-11-02T12:00:00-06:00",
        "2026-11-02T17:00:00-06:00",
        "2026-10-31T14:00:00-06:00",
    ],
)
def test_new_time_must_obey_lunch_closing_and_weekday_rules(calendar_api, start):
    _, events = calendar_api
    with pytest.raises(ValueError, match="horario"):
        reschedule(nuevo_inicio=start)
    events.patch.assert_not_called()


def test_conflict_preserves_original_event(calendar_api):
    _, events = calendar_api
    events.get.return_value.execute.return_value = meeting()
    events.list.return_value.execute.return_value = {
        "items": [meeting("other", NEW_START)]
    }
    with pytest.raises(ValueError, match="ocupado"):
        reschedule()
    events.patch.assert_not_called()
    events.insert.assert_not_called()


def test_reschedule_updates_only_time_of_same_event_and_notifies_attendees(
    calendar_api,
):
    _, events = calendar_api
    original = meeting()
    snapshot = deepcopy(original)
    events.get.return_value.execute.return_value = original
    events.list.return_value.execute.return_value = {"items": []}
    result = reschedule()
    assert result["estado"] == "reagendada"
    assert result["evento_id"] == original["id"]
    request = events.patch.call_args.kwargs
    assert request["eventId"] == original["id"]
    assert request["sendUpdates"] == "all"
    assert set(request["body"]) == {"start", "end"}
    assert request["body"]["end"]["dateTime"] == "2026-11-02T14:30:00-06:00"
    assert events.patch.return_value.headers["If-Match"] == original["etag"]
    assert original == snapshot
    events.insert.assert_not_called()


def test_source_event_does_not_conflict_with_its_own_new_interval(calendar_api):
    _, events = calendar_api
    original = meeting(start="2026-11-02T14:00:00-06:00")
    events.get.return_value.execute.return_value = original
    events.list.return_value.execute.return_value = {"items": [original]}
    result = reschedule(
        nuevo_inicio="2026-11-02T14:30:00-06:00",
        inicio_original_confirmado=NEW_START,
    )
    assert result["estado"] == "reagendada"


def test_a_change_to_original_time_requires_customer_confirmation_again(calendar_api):
    _, events = calendar_api
    events.get.return_value.execute.return_value = meeting(start=NEW_START)
    with pytest.raises(ValueError, match="original cambió"):
        reschedule(nuevo_inicio="2026-11-02T14:30:00-06:00")
    events.patch.assert_not_called()


def test_availability_checks_identity_before_excluding_original(calendar_api):
    _, events = calendar_api
    events.get.return_value.execute.return_value = meeting()
    with pytest.raises(ValueError, match="coincida"):
        calendar.consultar_horarios(
            "2026-11-02",
            "2 de la tarde",
            "stuart-original",
            "wrong@example.com",
        )
    events.list.assert_not_called()


def test_availability_for_reschedule_excludes_original_but_keeps_other_meetings(
    calendar_api,
):
    _, events = calendar_api
    original = meeting(start=NEW_START)
    events.get.return_value.execute.return_value = original
    events.list.return_value.execute.return_value = {"items": [original]}
    result = calendar.consultar_horarios(
        "2026-11-02", "2 de la tarde", "stuart-original", EMAIL
    )
    assert result["estado"] == "requested_time_available"
    events.list.return_value.execute.return_value = {
        "items": [original, meeting("other", NEW_START)]
    }
    result = calendar.consultar_horarios(
        "2026-11-02", "2 de la tarde", "stuart-original", EMAIL
    )
    assert result["estado"] == "requested_time_unavailable"


def test_all_day_time_off_blocks_reschedule(calendar_api):
    _, events = calendar_api
    events.get.return_value.execute.return_value = meeting()
    events.list.return_value.execute.return_value = {
        "items": [
            {
                "id": "vacation",
                "start": {"date": "2026-11-02"},
                "end": {"date": "2026-11-03"},
            }
        ]
    }
    with pytest.raises(ValueError, match="ocupado"):
        reschedule()
    events.patch.assert_not_called()


@pytest.mark.parametrize("operation", [reschedule, cancel])
@pytest.mark.parametrize("email", ["", "correo sin arroba"])
def test_modification_requires_email_before_any_calendar_access(
    calendar_api, operation, email
):
    service, _ = calendar_api
    with pytest.raises(ValueError, match="correo"):
        operation(correo_confirmado=email)
    service.events.assert_not_called()


def test_search_requires_email_before_any_calendar_access(calendar_api):
    service, _ = calendar_api
    with pytest.raises(ValueError, match="correo"):
        calendar.buscar_reuniones("")
    service.events.assert_not_called()


def test_cancellation_requires_explicit_confirmation(calendar_api):
    service, _ = calendar_api
    with pytest.raises(ValueError, match="confirmación explícita"):
        cancel(confirmacion_usuario=False)
    service.events.assert_not_called()


def test_cancellation_rechecks_email_of_selected_event(calendar_api):
    _, events = calendar_api
    events.get.return_value.execute.return_value = meeting()
    with pytest.raises(ValueError, match="coincida"):
        cancel(correo_confirmado="other@example.com")
    events.delete.assert_not_called()


def test_cannot_cancel_unrelated_event_even_if_email_matches(calendar_api):
    _, events = calendar_api
    unrelated = meeting()
    unrelated["summary"] = "Reunión personal"
    events.get.return_value.execute.return_value = unrelated
    with pytest.raises(ValueError, match="coincida"):
        cancel()
    events.delete.assert_not_called()


def test_cancellation_rejects_a_changed_original_time(calendar_api):
    _, events = calendar_api
    events.get.return_value.execute.return_value = meeting(start=NEW_START)
    with pytest.raises(ValueError, match="cambió de horario"):
        cancel()
    events.delete.assert_not_called()


def test_cancellation_rejects_past_meetings(calendar_api):
    _, events = calendar_api
    events.get.return_value.execute.return_value = meeting(
        start="2026-10-29T10:30:00-06:00"
    )
    with pytest.raises(ValueError, match="ya comenzó"):
        cancel()
    events.delete.assert_not_called()


@pytest.mark.parametrize("operation", [reschedule, cancel])
def test_series_parent_cannot_be_modified_instead_of_single_appointment(
    calendar_api, operation
):
    _, events = calendar_api
    series = meeting()
    series["recurrence"] = ["RRULE:FREQ=WEEKLY"]
    events.get.return_value.execute.return_value = series
    with pytest.raises(ValueError, match="serie completa"):
        operation()
    events.delete.assert_not_called()
    events.patch.assert_not_called()


def test_cancellation_deletes_only_selected_event_and_notifies_invitees(calendar_api):
    _, events = calendar_api
    original = meeting()
    events.get.return_value.execute.return_value = original
    result = cancel()
    assert result["estado"] == "cancelada"
    assert result["evento_id"] == "stuart-original"
    assert result["notificacion_enviada_a"] == EMAIL
    events.delete.assert_called_once_with(
        calendarId="primary", eventId="stuart-original", sendUpdates="all"
    )
    assert events.delete.return_value.headers["If-Match"] == original["etag"]
    events.delete.return_value.execute.assert_called_once_with()
    events.insert.assert_not_called()
    events.patch.assert_not_called()


@pytest.mark.parametrize("status", [412, 403])
def test_cancellation_does_not_report_success_after_google_error(calendar_api, status):
    _, events = calendar_api
    events.get.return_value.execute.return_value = meeting()
    events.delete.return_value.execute.side_effect = HttpError(
        Response({"status": str(status)}), b'{"error":{"message":"rejected"}}'
    )
    with pytest.raises(RuntimeError):
        cancel()
