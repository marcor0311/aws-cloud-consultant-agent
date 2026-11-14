"""MCP tools for checking and booking 30-minute Stuart meetings."""

import hashlib
import logging
import os
import re
import sys
from datetime import date, datetime, time, timedelta

from googleapiclient.errors import HttpError
from mcp.server.mcpserver import MCPServer

from src.config import load_environment
from src.domain.client_codes import normalize_client_code, prepare_client_confirmation
from src.domain.scheduling import (
    BOOKING_HORIZON,
    MEETING_DURATION,
    MONTHS_ES,
    TIME_ZONE,
    TIME_ZONE_NAME,
    WEEKDAYS_ES,
    _day_slots,
    _format_available_ranges,
    _is_within_policy,
    _parse_requested_date,
    _parse_requested_time,
    _slot_is_free,
    _time_phrase,
)
from src.integrations.access_client import AccessClient
from src.integrations.google_calendar import _calendar_ids, _calendar_service

load_environment()
if os.getenv("CALENDAR_ASSISTANT_MODE") == "mock":
    from src.integrations.mock_calendar import MockDateTime
    from src.integrations.mock_network import install_mock_network_guard

    install_mock_network_guard()
    datetime = MockDateTime
logging.basicConfig(
    level=logging.INFO,
    format="[calendar-mcp] %(levelname)s %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("calendar_mcp")


mcp = MCPServer("Stuart Calendar")
_access = AccessClient()


def _require_access(operation: str, email: str = "") -> dict | None:
    return _access.require(operation, email)


@mcp.tool()
def preparar_confirmacion_cliente(codigo_transcrito: str) -> dict:
    """Normaliza el código dictado (también letras fonéticas) y prepara su confirmación.

    No consulta registros ni autentica. Lee letras y números por separado y espera confirmación.
    """
    return prepare_client_confirmation(codigo_transcrito)


@mcp.tool()
def iniciar_verificacion_cliente(codigo_cliente: str) -> dict:
    """Solo tras confirmar el código de cliente: envía OTP al correo aprobado sin revelarlo.

    No acepta correos alternativos, no registra clientes y no permite acceder a la agenda.
    """
    return _access.start(normalize_client_code(codigo_cliente))


@mcp.tool()
def validar_codigo_correo(codigo: str) -> dict:
    """Valida en el backend los seis dígitos dictados, conservando ceros iniciales.

    Solo estado=verified permite continuar al calendario. Nunca inventes un código.
    """
    return _access.verify(codigo)


@mcp.tool()
def reenviar_codigo_correo() -> dict:
    """Solicita un código nuevo si la persona lo pide; respeta la espera del backend."""
    return _access.resend()


def _parse_rfc3339(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("La fecha debe incluir zona horaria.")
    return parsed.astimezone(TIME_ZONE)


def _get_busy_intervals(
    service, start: datetime, end: datetime
) -> list[tuple[datetime, datetime]]:
    calendar_ids = _calendar_ids(service)
    logger.info(
        "Consultando ocupación entre %s y %s en %d calendario(s).",
        start.astimezone(TIME_ZONE).strftime("%Y-%m-%d %H:%M"),
        end.astimezone(TIME_ZONE).strftime("%Y-%m-%d %H:%M"),
        len(calendar_ids),
    )
    response = (
        service.freebusy()
        .query(
            body={
                "timeMin": start.isoformat(),
                "timeMax": end.isoformat(),
                "timeZone": TIME_ZONE_NAME,
                "items": [{"id": calendar_id} for calendar_id in calendar_ids],
            }
        )
        .execute()
    )
    calendars = response.get("calendars", {})
    if any(
        calendar_id not in calendars or calendars[calendar_id].get("errors")
        for calendar_id in calendar_ids
    ):
        for calendar_number, calendar_id in enumerate(calendar_ids, start=1):
            errors = calendars.get(calendar_id, {}).get("errors", [])
            if errors:
                logger.error(
                    "Google rechazó el calendario %d: %s",
                    calendar_number,
                    ", ".join(
                        error.get("reason", "error desconocido") for error in errors
                    ),
                )
        raise RuntimeError("Google Calendar no pudo consultar ese calendario.")
    busy_intervals = []
    for calendar_number, calendar_id in enumerate(calendar_ids, start=1):
        calendar_busy = calendars.get(calendar_id, {}).get("busy", [])
        logger.info(
            "Calendario %d: Google devolvió %d bloque(s) ocupado(s).",
            calendar_number,
            len(calendar_busy),
        )
        for item in calendar_busy:
            busy_start = _parse_rfc3339(item["start"])
            busy_end = _parse_rfc3339(item["end"])
            busy_intervals.append((busy_start, busy_end))
            logger.info(
                "Calendario %d ocupado: %s-%s (hora de Costa Rica).",
                calendar_number,
                busy_start.strftime("%Y-%m-%d %H:%M"),
                busy_end.strftime("%H:%M"),
            )
    if not busy_intervals:
        logger.info("Google no devolvió bloques ocupados en ese rango.")
    return busy_intervals


def _normalize_email(value: str) -> str:
    # Speech transcription may insert spaces inside an otherwise valid address.
    return re.sub(r"\s+", "", value).casefold()


def _require_confirmed_email(value: str) -> str:
    email = _normalize_email(value)
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise ValueError(
            "No hay un correo aprobado válido en la sesión; verifique el OTP del cliente."
        )
    return email


@mcp.tool()
def consultar_horarios(
    fecha_solicitada: str = "",
    hora_solicitada: str = "",
    evento_a_reagendar: str = "",
    correo_confirmado: str = "",
) -> dict[str, object]:
    """Consulta espacios libres de 30 minutos dentro de las próximas dos semanas.

    Solo ofrece inicios en punto o y media: 08:00 a 11:30 y 13:00 a 16:30, hora de Costa Rica.
    Los rangos son de horas de inicio; ninguna cita cruza el almuerzo o el cierre.

    Args:
        fecha_solicitada: Expresión de fecha de la persona, por ejemplo una fecha
            concreta, un día de la semana o una fecha relativa. Se interpreta en
            la zona horaria de Costa Rica y debe estar dentro de los próximos 14 días.
        hora_solicitada: Hora que la persona propone. La fecha también es necesaria
            para confirmar si ese espacio específico está libre.
        evento_a_reagendar: ID devuelto por buscar_reuniones, solo para reagendar.
        correo_confirmado: Opcional. Omitir para usar el correo aprobado de la sesión verificada.
    """
    if denied := _require_access("availability", correo_confirmado):
        return denied
    correo_confirmado = correo_confirmado or _access.email
    now = datetime.now(TIME_ZONE).replace(second=0, microsecond=0)
    horizon_end = now + BOOKING_HORIZON
    requested_day = None
    if fecha_solicitada.strip():
        requested_day = _parse_requested_date(fecha_solicitada, now)
        if not now.date() <= requested_day <= horizon_end.date():
            raise ValueError("La fecha debe estar dentro de los próximos 14 días.")

    if hora_solicitada.strip() and requested_day is None:
        raise ValueError("Primero hace falta saber qué fecha quiere consultar.")

    requested_time = (
        _parse_requested_time(hora_solicitada) if hora_solicitada.strip() else None
    )
    if evento_a_reagendar:
        correo_confirmado = _require_confirmed_email(correo_confirmado)
    service = _calendar_service()
    if evento_a_reagendar:
        _get_manageable_event(service, evento_a_reagendar, correo_confirmado, now)
        busy = _busy_except_event(service, now, horizon_end, evento_a_reagendar)
    else:
        busy = _get_busy_intervals(service, now, horizon_end)
    days = (
        [requested_day]
        if requested_day
        else [
            now.date() + timedelta(days=offset)
            for offset in range((horizon_end.date() - now.date()).days + 1)
        ]
    )

    available = []
    for day in days:
        if day.weekday() >= 5:
            continue
        for slot in _day_slots(day, now):
            if _is_within_policy(slot, now) and _slot_is_free(slot, busy):
                available.append(
                    {
                        "inicio": slot.isoformat(timespec="minutes"),
                        "fin": (slot + MEETING_DURATION).isoformat(timespec="minutes"),
                        "hora_local": (
                            f"{WEEKDAYS_ES[slot.weekday()]} {slot.day} de "
                            f"{MONTHS_ES[slot.month - 1]} {_time_phrase(slot)}"
                        ),
                        "zona_horaria": TIME_ZONE_NAME,
                    }
                )

    by_day: dict[date, list[dict[str, str]]] = {}
    for slot in available:
        slot_day = datetime.fromisoformat(slot["inicio"]).date()
        by_day.setdefault(slot_day, []).append(slot)
    available_days = [
        {
            "fecha": day.isoformat(),
            "fecha_local": (
                f"{WEEKDAYS_ES[day.weekday()]} {day.day} de {MONTHS_ES[day.month - 1]}"
            ),
            "cantidad_horarios": len(day_slots),
            "rangos_disponibles": _format_available_ranges(day_slots),
        }
        for day, day_slots in by_day.items()
    ]
    selected_slot = (
        next(
            (
                slot
                for slot in available
                if datetime.fromisoformat(slot["inicio"]).time().replace(tzinfo=None)
                == requested_time
            ),
            None,
        )
        if requested_time
        else None
    )

    if requested_time is not None and selected_slot is not None:
        status = "requested_time_available"
        response_text = (
            f"Sí, hay espacio el {selected_slot['hora_local']}. "
            "Si le funciona, puedo ayudarle a agendarlo."
        )
    elif requested_time is not None:
        status = "requested_time_unavailable"
        response_text = _availability_message(
            available,
            prefix=f"No hay espacio el {WEEKDAYS_ES[requested_day.weekday()]} "
            f"{requested_day.day} de {MONTHS_ES[requested_day.month - 1]} "
            f"{_time_phrase(datetime.combine(requested_day, requested_time, TIME_ZONE))}.",
        )
    elif requested_day is not None:
        status = "availability_options"
        day_name = (
            f"{WEEKDAYS_ES[requested_day.weekday()]} {requested_day.day} "
            f"de {MONTHS_ES[requested_day.month - 1]}"
        )
        response_text = _availability_message(available, prefix=f"Para el {day_name}")
    else:
        status = "available_days"
        response_text = _available_days_message(available_days)

    logger.info(
        "Disponibilidad: estado=%s; opciones ofrecibles: %s",
        status,
        ", ".join(slot["hora_local"] for slot in available) or "ninguna",
    )
    return {
        "estado": status,
        "fecha_consultada": requested_day.isoformat()
        if requested_day
        else "próximos 14 días",
        "hora_solicitada": hora_solicitada,
        "horario_solicitado": selected_slot or {},
        "dias_disponibles": available_days,
        "rangos_disponibles": (
            _format_available_ranges(available) if requested_day else []
        ),
        "respuesta_para_decir": response_text,
    }


def _availability_message(options: list[dict[str, str]], prefix: str = "") -> str:
    if not options:
        if prefix:
            return f"{prefix} Ese día no quedan espacios disponibles. ¿Le sirve otra fecha?"
        return "No encontré espacios disponibles en los próximos días. ¿Quiere que revise otra fecha?"
    ranges = _format_available_ranges(options)
    options_text = "; y ".join(ranges)
    if prefix:
        return f"{prefix} tengo horarios de inicio disponibles {options_text}, cada media hora. ¿Qué horario le funciona?"
    return f"Tengo horarios de inicio disponibles {options_text}, cada media hora. ¿Qué horario le funciona?"


def _available_days_message(days: list[dict[str, object]]) -> str:
    if not days:
        return "No encontré espacios disponibles en las próximas dos semanas."
    dates = "; ".join(str(day["fecha_local"]) for day in days)
    return f"Hay disponibilidad en estas fechas: {dates}. ¿Qué día le queda mejor?"


@mcp.tool()
def agendar_reunion(
    inicio: str,
    nombre: str,
    correo_confirmado: str = "",
    tema: str = "",
) -> dict[str, str]:
    """Crea una invitación de 30 minutos después de verificar el OTP y confirmar la hora.

    Args:
        inicio: Hora elegida, en formato ISO 8601 con zona horaria, obtenida de consultar_horarios.
        nombre: Nombre confirmado de la persona invitada.
        correo_confirmado: Opcional. Omitir para usar el correo aprobado de la sesión verificada.
        tema: Resumen breve del proyecto o motivo de la reunión, si se conoce.
    """
    operation_started = datetime.now(TIME_ZONE).isoformat()
    if denied := _require_access("book", correo_confirmado):
        return denied
    correo_confirmado = correo_confirmado or _access.email
    email = _normalize_email(correo_confirmado)
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise ValueError("El correo confirmado no tiene un formato válido.")

    try:
        start = _parse_rfc3339(inicio)
    except (TypeError, ValueError) as error:
        raise ValueError(
            "La fecha debe incluir zona horaria en formato ISO 8601."
        ) from error

    now = datetime.now(TIME_ZONE).replace(second=0, microsecond=0)
    if not _is_within_policy(start, now):
        raise ValueError(
            "Ese horario no cumple las reglas: debe ser un espacio libre de 30 minutos, "
            "de lunes a viernes, con inicio entre 08:00 y 11:30 o entre 13:00 y 16:30, "
            "solo en punto o y media, dentro de los próximos 14 días."
        )

    service = _calendar_service()
    end = start + MEETING_DURATION
    busy = _get_busy_intervals(service, start, end)
    if not _slot_is_free(start, busy):
        logger.warning(
            "Reserva rechazada: %s-%s ya está ocupado.",
            start.strftime("%Y-%m-%d %H:%M"),
            end.strftime("%H:%M"),
        )
        raise ValueError(
            "Ese espacio ya no está disponible. Vuelve a consultar horarios y ofrece otras opciones."
        )

    description = (
        f"Reunión de 30 minutos con Stuart, gerente de Relaciones con el Cliente.\n"
        f"Participante: {nombre.strip()} ({email})."
    )
    if tema.strip():
        description += f"\nTema: {tema.strip()[:1000]}"

    event = {
        "id": hashlib.sha256(
            f"{_access.session_id}:{start.isoformat()}:{email}".encode()
        ).hexdigest(),
        "summary": f"Reunión con Stuart — {nombre.strip()}",
        "description": description,
        "start": {"dateTime": start.isoformat(), "timeZone": TIME_ZONE_NAME},
        "end": {"dateTime": end.isoformat(), "timeZone": TIME_ZONE_NAME},
        "attendees": [{"email": email, "displayName": nombre.strip()}],
        "extendedProperties": {
            "private": {
                "calendar_assistant": "stuart",
                "workflow_client_code": _access.client_code,
            }
        },
        "conferenceData": {
            "createRequest": {
                "requestId": hashlib.sha256(
                    f"{_access.session_id}:{start.isoformat()}".encode()
                ).hexdigest(),
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        },
    }
    try:
        created = (
            service.events()
            .insert(
                calendarId=_calendar_ids(service)[0],
                body=event,
                sendUpdates="all",
                conferenceDataVersion=1,
            )
            .execute()
        )
    except HttpError as error:
        raise RuntimeError("Google Calendar no pudo crear la invitación.") from error

    sync = _access.record_meeting(
        _calendar_ids(service)[0],
        created.get("id", ""),
        "scheduled",
        created.get("etag", ""),
        operation_started,
    )

    return {
        "estado": "agendada",
        "inicio": start.isoformat(timespec="minutes"),
        "fin": end.isoformat(timespec="minutes"),
        "duracion_minutos": "30",
        "zona_horaria": TIME_ZONE_NAME,
        "invitacion_enviada": "correo registrado",
        "organizador": created.get("organizer", {}).get(
            "email", os.getenv("GOOGLE_ACCOUNT_EMAIL", "").strip()
        ),
        "evento_id": created.get("id", ""),
        "enlace": created.get("htmlLink", ""),
        "enlace_meet": created.get("hangoutLink", ""),
        "preparacion_estado": sync,
    }


def _list_events(service, start: datetime, end: datetime):
    page_token = None
    while True:
        response = (
            service.events()
            .list(
                calendarId=_calendar_ids(service)[0],
                timeMin=start.isoformat(),
                timeMax=end.isoformat(),
                singleEvents=True,
                orderBy="startTime",
                showDeleted=False,
                maxResults=250,
                pageToken=page_token,
            )
            .execute()
        )
        yield from response.get("items", [])
        page_token = response.get("nextPageToken")
        if not page_token:
            return


def _event_times(event: dict) -> tuple[datetime, datetime]:
    def parse_boundary(value: dict) -> datetime:
        if value.get("dateTime"):
            return _parse_rfc3339(value["dateTime"])
        return datetime.combine(date.fromisoformat(value["date"]), time.min, TIME_ZONE)

    return parse_boundary(event["start"]), parse_boundary(event["end"])


def _matches_stuart_meeting(event: dict, email: str) -> bool:
    if not email or event.get("status") == "cancelled":
        return False
    if not event.get("organizer", {}).get("self"):
        return False
    if not any(
        _normalize_email(attendee.get("email", "")) == email
        for attendee in event.get("attendees", [])
    ):
        return False
    properties = event.get("extendedProperties", {}).get("private", {})
    marked = properties.get("calendar_assistant") == "stuart"
    legacy = " ".join(event.get("summary", "").casefold().split()).startswith(
        "reunión con stuart — "
    ) and event.get("description", "").startswith("Reunión de 30 minutos con Stuart,")
    if not (marked or legacy) or "dateTime" not in event.get("start", {}):
        return False
    start, end = _event_times(event)
    return end - start == MEETING_DURATION


def _get_manageable_event(service, evento_id, correo, now) -> dict:
    email = _require_confirmed_email(correo)
    event = (
        service.events()
        .get(calendarId=_calendar_ids(service)[0], eventId=evento_id)
        .execute()
    )
    if not _matches_stuart_meeting(event, email):
        raise ValueError("No encontré una cita de Stuart que coincida con ese correo.")
    if event.get("recurrence"):
        raise ValueError(
            "Selecciona una cita concreta de la búsqueda; no se modifica la serie completa."
        )
    if _event_times(event)[0] <= now:
        raise ValueError(
            "La cita ya comenzó o pasó; solo se pueden modificar citas futuras."
        )
    return event


def _busy_except_event(service, start, end, excluded_id):
    busy = []
    for event in _list_events(service, start, end):
        if (
            event.get("id") == excluded_id
            or event.get("status") == "cancelled"
            or event.get("transparency") == "transparent"
            or event.get("eventType") == "workingLocation"
            or any(
                attendee.get("self") and attendee.get("responseStatus") == "declined"
                for attendee in event.get("attendees", [])
            )
        ):
            continue
        busy.append(_event_times(event))
    logger.info(
        "Reagendamiento: se recuperaron %d bloques ocupados, excluyendo la cita original.",
        len(busy),
    )
    return busy


@mcp.tool()
def buscar_reuniones(
    correo_confirmado: str = "", fecha_original: str = ""
) -> dict[str, object]:
    """Busca citas futuras de Stuart solo por coincidencia exacta del correo invitado.

    Devuelve hasta diez citas en el próximo año. Si hay varias, pregunta cuál
    quiere modificar antes de reagendar o cancelar. fecha_original acota a un día.
    """
    if denied := _require_access("search", correo_confirmado):
        return denied
    correo_confirmado = correo_confirmado or _access.email
    now = datetime.now(TIME_ZONE)
    start, end = now, now + timedelta(days=365)
    if fecha_original.strip():
        day = _parse_requested_date(fecha_original, now)
        start = max(now, datetime.combine(day, time.min, TIME_ZONE))
        end = datetime.combine(day + timedelta(days=1), time.min, TIME_ZONE)
        if end <= start:
            raise ValueError("Solo se buscan citas futuras.")
    email = _require_confirmed_email(correo_confirmado)
    matches = []
    for event in _list_events(_calendar_service(), start, end):
        if not _matches_stuart_meeting(event, email):
            continue
        event_start, event_end = _event_times(event)
        if event_start <= now:
            continue
        matches.append(
            {
                "evento_id": event["id"],
                "inicio": event_start.isoformat(timespec="minutes"),
                "fin": event_end.isoformat(timespec="minutes"),
                "fecha_local": (
                    f"{WEEKDAYS_ES[event_start.weekday()]} {event_start.day} de "
                    f"{MONTHS_ES[event_start.month - 1]} {_time_phrase(event_start)}"
                ),
            }
        )
        if len(matches) > 10:
            break
    logger.info(
        "Búsqueda de citas de Stuart: %d coincidencia(s).", min(len(matches), 10)
    )
    return {"reuniones": matches[:10], "hay_mas": len(matches) > 10}


@mcp.tool()
def reagendar_reunion(
    evento_id: str,
    nuevo_inicio: str,
    inicio_original_confirmado: str,
    correo_confirmado: str = "",
    confirmacion_usuario: bool = False,
) -> dict[str, str]:
    """Mueve la cita elegida tras confirmar explícitamente la cita original y la nueva hora.

    Conserva el mismo evento y sus invitados. Revalida el correo invitado,
    disponibilidad, jornada y duración. No crea una segunda invitación.
    """
    operation_started = datetime.now(TIME_ZONE).isoformat()
    if denied := _require_access("reschedule", correo_confirmado):
        return denied
    correo_confirmado = correo_confirmado or _access.email
    email = _require_confirmed_email(correo_confirmado)
    if not confirmacion_usuario:
        raise ValueError(
            "Espera la confirmación explícita del cliente antes de mover la cita."
        )
    now = datetime.now(TIME_ZONE)
    start = _parse_rfc3339(nuevo_inicio)
    if not _is_within_policy(start, now):
        raise ValueError(
            "El nuevo horario debe iniciar en punto o y media, entre 08:00 y 11:30 o entre 13:00 y 16:30, en un día hábil de las próximas dos semanas."
        )
    service = _calendar_service()
    original = _get_manageable_event(service, evento_id, email, now)
    previous_start, _ = _event_times(original)
    if previous_start != _parse_rfc3339(inicio_original_confirmado):
        raise ValueError(
            "La cita original cambió de horario. Vuelve a buscarla y confirma el cambio con la persona."
        )
    if previous_start == start:
        return {
            "estado": "sin_cambios",
            "evento_id": evento_id,
            "inicio": start.isoformat(),
        }
    end = start + MEETING_DURATION
    if not _slot_is_free(start, _busy_except_event(service, start, end, evento_id)):
        raise ValueError(
            "El nuevo horario ya está ocupado. Consulta otras opciones; la cita original sigue intacta."
        )
    try:
        request = service.events().patch(
            calendarId=_calendar_ids(service)[0],
            eventId=evento_id,
            body={
                "start": {"dateTime": start.isoformat(), "timeZone": TIME_ZONE_NAME},
                "end": {"dateTime": end.isoformat(), "timeZone": TIME_ZONE_NAME},
            },
            sendUpdates="all",
        )
        if original.get("etag"):
            request.headers["If-Match"] = original["etag"]
        updated = request.execute()
    except HttpError as error:
        if error.resp.status == 412:
            raise RuntimeError(
                "La cita cambió mientras conversábamos. Vuelve a buscarla y confirma el cambio."
            ) from error
        raise RuntimeError(
            "Google Calendar no pudo reagendar la cita; no confirmes el cambio."
        ) from error
    logger.info("Cita reagendada conservando el evento original.")
    sync = _access.record_meeting(
        _calendar_ids(service)[0],
        evento_id,
        "rescheduled",
        updated.get("etag", ""),
        operation_started,
    )
    return {
        "estado": "reagendada",
        "evento_id": updated.get("id", evento_id),
        "inicio_anterior": previous_start.isoformat(timespec="minutes"),
        "inicio": start.isoformat(timespec="minutes"),
        "fin": end.isoformat(timespec="minutes"),
        "duracion_minutos": "30",
        "zona_horaria": TIME_ZONE_NAME,
        "invitacion_actualizada": "correo registrado",
        "preparacion_estado": sync,
    }


@mcp.tool()
def cancelar_reunion(
    evento_id: str,
    inicio_original_confirmado: str,
    correo_confirmado: str = "",
    confirmacion_usuario: bool = False,
) -> dict[str, str]:
    """Cancela una cita futura de Stuart encontrada por el correo del invitado.

    Primero verifica el OTP y busca la cita con buscar_reuniones,
    repite su fecha y hora y espera un sí explícito para cancelar. Revalida
    la coincidencia del invitado y la cita antes de notificar la cancelación.
    """
    operation_started = datetime.now(TIME_ZONE).isoformat()
    if denied := _require_access("cancel", correo_confirmado):
        return denied
    correo_confirmado = correo_confirmado or _access.email
    email = _require_confirmed_email(correo_confirmado)
    if not confirmacion_usuario:
        raise ValueError(
            "Espera la confirmación explícita del cliente antes de cancelar la cita."
        )
    now = datetime.now(TIME_ZONE)
    service = _calendar_service()
    original = _get_manageable_event(service, evento_id, email, now)
    original_start, _ = _event_times(original)
    if original_start != _parse_rfc3339(inicio_original_confirmado):
        raise ValueError(
            "La cita cambió de horario. Vuelve a buscarla y confirma cuál quiere cancelar."
        )
    try:
        request = service.events().delete(
            calendarId=_calendar_ids(service)[0],
            eventId=evento_id,
            sendUpdates="all",
        )
        if original.get("etag"):
            request.headers["If-Match"] = original["etag"]
        request.execute()
    except HttpError as error:
        if error.resp.status == 412:
            raise RuntimeError(
                "La cita cambió mientras conversábamos. Vuelve a buscarla y confirma la cancelación."
            ) from error
        raise RuntimeError(
            "Google Calendar no pudo cancelar la cita; no confirmes la cancelación."
        ) from error
    logger.info("Cancelación de una cita de Stuart completada.")
    sync = _access.record_meeting(
        _calendar_ids(service)[0],
        evento_id,
        "cancelled",
        original.get("etag", ""),
        operation_started,
    )
    return {
        "estado": "cancelada",
        "evento_id": evento_id,
        "inicio_anterior": original_start.isoformat(timespec="minutes"),
        "zona_horaria": TIME_ZONE_NAME,
        "notificacion_enviada": "correo registrado",
        "preparacion_estado": sync,
    }


if __name__ == "__main__":
    try:
        mcp.run(transport="stdio")
    finally:
        _access.close()
