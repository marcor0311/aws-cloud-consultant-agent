"""MCP tools for checking and booking 30-minute Stuart meetings."""

import logging
import os
import re
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import dateparser
from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from mcp.server.fastmcp import FastMCP
from text_to_num import alpha2digit

try:
    from .access_client import AccessClient
except ImportError:  # Executed directly by the stdio MCP launcher.
    from access_client import AccessClient

PROJECT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_DIR / ".env.local")
logging.basicConfig(
    level=logging.INFO,
    format="[calendar-mcp] %(levelname)s %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("calendar_mcp")

TIME_ZONE_NAME = "America/Costa_Rica"
TIME_ZONE = ZoneInfo(TIME_ZONE_NAME)
WORK_START = time(8, 0)
WORK_END = time(17, 0)
LUNCH_START = time(12, 0)
LUNCH_END = time(13, 0)
MEETING_DURATION = timedelta(minutes=30)
BOOKING_HORIZON = timedelta(days=14)
WEEKDAYS_ES = (
    "lunes",
    "martes",
    "miércoles",
    "jueves",
    "viernes",
    "sábado",
    "domingo",
)
MONTHS_ES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)
SCOPES = [
    "https://www.googleapis.com/auth/calendar.freebusy",
    "https://www.googleapis.com/auth/calendar.events.owned",
]

mcp = FastMCP("Stuart Calendar")
_access = AccessClient()


def _require_access(operation: str, email: str = "") -> None:
    _access.require(operation, email)


@mcp.tool()
def iniciar_verificacion_correo(correo_confirmado: str) -> dict:
    """Tras confirmar el deletreo, consulta el registro externo y solicita el código al backend.

    Si no está registrado, deriva al asesor de negocio. code_sent indica envío
    aceptado, no correo verificado. No llames herramientas de calendario todavía.
    """
    return _access.start(_require_confirmed_email(correo_confirmado))


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


def _configured_path(variable: str, default_name: str) -> Path:
    configured = Path(os.getenv(variable, default_name)).expanduser()
    return configured if configured.is_absolute() else PROJECT_DIR / configured


def _calendar_ids(_service) -> list[str]:
    calendar_id = os.getenv("GOOGLE_CALENDAR_ID", "primary")
    return ["primary" if calendar_id == "all" else calendar_id]


def _save_credentials(credentials: Credentials, token_file: Path) -> None:
    token_file.write_text(credentials.to_json(), encoding="utf-8")
    token_file.chmod(0o600)


def _calendar_service():
    token_file = _configured_path(
        "GOOGLE_OAUTH_TOKEN_FILE", "secrets/google_calendar_token.json"
    )
    if not token_file.is_file():
        raise RuntimeError(
            "Google Calendar aún no está autorizado. Ejecuta `uv run "
            "python src/google_oauth.py` y autoriza la cuenta configurada."
        )

    credentials = Credentials.from_authorized_user_file(str(token_file), SCOPES)
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        _save_credentials(credentials, token_file)
    if not credentials.valid:
        raise RuntimeError(
            "La autorización de Google expiró. Vuelve a ejecutar "
            "`uv run python src/google_oauth.py`."
        )
    return build("calendar", "v3", credentials=credentials, cache_discovery=False)


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


def _is_within_policy(start: datetime, now: datetime) -> bool:
    local_start = start.astimezone(TIME_ZONE)
    local_end = local_start + MEETING_DURATION
    return (
        now <= local_start <= now + BOOKING_HORIZON
        and local_start.weekday() < 5
        and local_start.minute in (0, 30)
        and local_start.second == 0
        and local_start.microsecond == 0
        and WORK_START <= local_start.time().replace(tzinfo=None) < WORK_END
        and local_end.time().replace(tzinfo=None) <= WORK_END
        and not (
            local_start.time().replace(tzinfo=None) < LUNCH_END
            and local_end.time().replace(tzinfo=None) > LUNCH_START
        )
    )


def _slot_is_free(
    start: datetime, busy_intervals: list[tuple[datetime, datetime]]
) -> bool:
    end = start + MEETING_DURATION
    return not any(
        busy_start < end and busy_end > start for busy_start, busy_end in busy_intervals
    )


def _day_slots(day: date, now: datetime):
    slot_start = datetime.combine(day, WORK_START, TIME_ZONE)
    day_end = datetime.combine(day, WORK_END, TIME_ZONE)
    while slot_start + MEETING_DURATION <= day_end:
        if slot_start >= now:
            yield slot_start
        slot_start += MEETING_DURATION


def _spoken_time(value: datetime) -> str:
    local_time = value.astimezone(TIME_ZONE)
    clock = _clock_only(local_time)
    if local_time.hour < 12:
        period = "de la mañana"
    elif local_time.hour == 12:
        period = "del mediodía"
    else:
        period = "de la tarde"
    return f"{clock} {period}"


def _clock_only(value: datetime) -> str:
    local_time = value.astimezone(TIME_ZONE)
    hour = local_time.hour % 12 or 12
    return f"{hour}:{local_time.minute:02d}"


def _format_available_ranges(slots: list[dict[str, str]]) -> list[str]:
    if not slots:
        return []

    ranges: list[tuple[datetime, datetime]] = []
    for slot in slots:
        start = datetime.fromisoformat(slot["inicio"]).astimezone(TIME_ZONE)
        end = datetime.fromisoformat(slot["fin"]).astimezone(TIME_ZONE)
        if ranges and ranges[-1][1] == start:
            ranges[-1] = (ranges[-1][0], end)
        else:
            ranges.append((start, end))

    formatted = []
    for start, end in ranges:
        if end - start == MEETING_DURATION:
            formatted.append(f"a las {_spoken_time(start)}")
        elif start.hour < 12 and end.hour == 12:
            formatted.append(
                f"de {_clock_only(start)} de la mañana a {_spoken_time(end)}"
            )
        else:
            start_period = "de la mañana" if start.hour < 12 else "de la tarde"
            end_period = "de la mañana" if end.hour < 12 else "de la tarde"
            if start_period == end_period:
                formatted.append(
                    f"de {_clock_only(start)} a {_clock_only(end)} {end_period}"
                )
            else:
                formatted.append(f"de {_spoken_time(start)} a {_spoken_time(end)}")
    return formatted


def _parse_requested_date(value: str, now: datetime) -> date:
    phrase = " ".join(value.strip().split())
    try:
        return date.fromisoformat(phrase)
    except ValueError:
        pass

    phrase = alpha2digit(phrase, "es", threshold=0)
    phrase = re.sub(
        r"\b(el|la|este|esta|próximo|próxima|siguiente|next)\b",
        " ",
        phrase,
        flags=re.IGNORECASE,
    )
    phrase = re.sub(r"\bque viene\b", " ", phrase, flags=re.IGNORECASE)
    phrase = re.sub(r"\bdentro de\b", "en", phrase, flags=re.IGNORECASE)
    phrase = " ".join(phrase.split())
    parsed = dateparser.parse(
        phrase,
        languages=["es", "en"],
        settings={
            "DATE_ORDER": "DMY",
            "PREFER_DATES_FROM": "future",
            "RELATIVE_BASE": now,
            "RETURN_AS_TIMEZONE_AWARE": True,
            "TIMEZONE": TIME_ZONE_NAME,
        },
    )
    if parsed is None:
        raise ValueError(
            "No pude interpretar esa fecha. Pídele a la persona que la aclare."
        )
    return parsed.astimezone(TIME_ZONE).date()


def _parse_requested_time(value: str) -> time:
    phrase = alpha2digit(" ".join(value.strip().split()), "es", threshold=0)
    normalized = phrase.casefold().replace(".", "")
    is_pm = bool(re.search(r"\b(pm|de la tarde|de la noche)\b", normalized))
    is_am = bool(re.search(r"\b(am|de la mañana)\b", normalized))
    normalized = re.sub(
        r"\b(a las|a la|las|la|de la tarde|de la noche|de la mañana|p\s*m|a\s*m)\b",
        " ",
        normalized,
    )
    normalized = re.sub(r"\s+y\s+media\b", ":30", normalized)
    match = re.search(r"(?<!\d)(\d{1,2})(?::(\d{2}))?(?!\d)", normalized)
    if not match:
        raise ValueError("No pude interpretar la hora; pide que la aclare.")

    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    if not 0 <= hour <= 23 or minute not in (0, 30):
        raise ValueError("La hora debe corresponder a un espacio de media hora.")
    if is_pm and not is_am and 1 <= hour <= 11:
        hour += 12
    elif not is_pm and not is_am and 1 <= hour <= 7:
        # In the stated 08:00-17:00 work window, these hours mean afternoon.
        hour += 12
    return time(hour, minute)


def _normalize_email(value: str) -> str:
    # Speech transcription may insert spaces inside an otherwise valid address.
    return re.sub(r"\s+", "", value).casefold()


def _require_confirmed_email(value: str) -> str:
    email = _normalize_email(value)
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise ValueError("Primero pide el correo y confirma que esté bien escrito.")
    return email


def _spell_email(value: str) -> str:
    names = {
        "a": "a",
        "b": "be",
        "c": "ce",
        "d": "de",
        "e": "e",
        "f": "efe",
        "g": "ge",
        "h": "hache",
        "i": "i",
        "j": "jota",
        "k": "ka",
        "l": "ele",
        "m": "eme",
        "n": "ene",
        "o": "o",
        "p": "pe",
        "q": "cu",
        "r": "erre",
        "s": "ese",
        "t": "te",
        "u": "u",
        "v": "uve",
        "w": "doble u",
        "x": "equis",
        "y": "ye",
        "z": "zeta",
        "0": "cero",
        "1": "uno",
        "2": "dos",
        "3": "tres",
        "4": "cuatro",
        "5": "cinco",
        "6": "seis",
        "7": "siete",
        "8": "ocho",
        "9": "nueve",
        "@": "arroba",
        ".": "punto",
        "-": "guion",
        "_": "guion bajo",
        "+": "más",
        "%": "por ciento",
    }
    return ", ".join(names[char] for char in value)


@mcp.tool()
def preparar_confirmacion_correo(correo_transcrito: str) -> dict[str, str]:
    """Normaliza un correo dictado y lo deletrea para confirmación explícita."""
    email = _normalize_email(correo_transcrito)
    if len(email) > 254 or not re.fullmatch(
        r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", email
    ):
        logger.info("No se pudo validar el formato del correo dictado.")
        return {
            "estado": "invalido",
            "correo_normalizado": "",
            "respuesta_para_decir": (
                "No pude reconocer bien el correo. ¿Podría repetirlo o deletrearlo?"
            ),
        }

    username, domain = email.rsplit("@", 1)
    domain_spelling = (
        "gmail punto com" if domain == "gmail.com" else _spell_email(domain)
    )
    spelling = f"{_spell_email(username)}, arroba, {domain_spelling}"
    logger.info("Correo dictado normalizado y listo para confirmar letra por letra.")
    return {
        "estado": "pendiente_confirmacion",
        "correo_normalizado": email,
        "correo_deletreado": spelling,
        "respuesta_para_decir": (
            f"Entendí el correo así: {spelling}. ¿Lo anoté correctamente?"
        ),
    }


@mcp.tool()
def consultar_horarios(
    fecha_solicitada: str = "",
    hora_solicitada: str = "",
    evento_a_reagendar: str = "",
    correo_confirmado: str = "",
) -> dict[str, object]:
    """Consulta espacios libres de 30 minutos dentro de las próximas dos semanas.

    No ofrece reuniones durante el almuerzo de 12:00 a 13:00, hora de Costa Rica.

    Args:
        fecha_solicitada: Expresión de fecha de la persona, por ejemplo una fecha
            concreta, un día de la semana o una fecha relativa. Se interpreta en
            la zona horaria de Costa Rica y debe estar dentro de los próximos 14 días.
        hora_solicitada: Hora que la persona propone. La fecha también es necesaria
            para confirmar si ese espacio específico está libre.
        evento_a_reagendar: ID devuelto por buscar_reuniones, solo para reagendar.
        correo_confirmado: Correo confirmado del invitado de la cita original.
    """
    _require_access("availability", correo_confirmado)
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
                            f"{MONTHS_ES[slot.month - 1]} a las {_spoken_time(slot)}"
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
            f"a las {_spoken_time(datetime.combine(requested_day, requested_time, TIME_ZONE))}.",
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
        return (
            f"{prefix} tengo disponibilidad {options_text}. ¿Qué horario le funciona?"
        )
    return f"Tengo disponibilidad {options_text}. ¿Qué horario le funciona?"


def _available_days_message(days: list[dict[str, object]]) -> str:
    if not days:
        return "No encontré espacios disponibles en las próximas dos semanas."
    dates = "; ".join(str(day["fecha_local"]) for day in days)
    return f"Hay disponibilidad en estas fechas: {dates}. ¿Qué día le queda mejor?"


@mcp.tool()
def agendar_reunion(
    inicio: str,
    nombre: str,
    correo_confirmado: str,
    tema: str = "",
) -> dict[str, str]:
    """Crea una invitación de 30 minutos después de que la persona confirme correo y hora.

    Args:
        inicio: Hora elegida, en formato ISO 8601 con zona horaria, obtenida de consultar_horarios.
        nombre: Nombre confirmado de la persona invitada.
        correo_confirmado: Correo que la persona confirmó explícitamente.
        tema: Resumen breve del proyecto o motivo de la reunión, si se conoce.
    """
    _require_access("book", correo_confirmado)
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
            "de lunes a viernes, entre 08:00 y 17:00, sin cruzar el almuerzo de "
            "12:00 a 13:00, dentro de los próximos 14 días."
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
        "summary": f"Reunión con Stuart — {nombre.strip()}",
        "description": description,
        "start": {"dateTime": start.isoformat(), "timeZone": TIME_ZONE_NAME},
        "end": {"dateTime": end.isoformat(), "timeZone": TIME_ZONE_NAME},
        "attendees": [{"email": email, "displayName": nombre.strip()}],
        "extendedProperties": {"private": {"calendar_assistant": "stuart"}},
    }
    try:
        created = (
            service.events()
            .insert(
                calendarId=_calendar_ids(service)[0],
                body=event,
                sendUpdates="all",
            )
            .execute()
        )
    except HttpError as error:
        raise RuntimeError("Google Calendar no pudo crear la invitación.") from error

    return {
        "estado": "agendada",
        "inicio": start.isoformat(timespec="minutes"),
        "fin": end.isoformat(timespec="minutes"),
        "duracion_minutos": "30",
        "zona_horaria": TIME_ZONE_NAME,
        "invitacion_enviada_a": email,
        "organizador": created.get("organizer", {}).get(
            "email", os.getenv("GOOGLE_ACCOUNT_EMAIL", "").strip()
        ),
        "evento_id": created.get("id", ""),
        "enlace": created.get("htmlLink", ""),
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
    correo_confirmado: str, fecha_original: str = ""
) -> dict[str, object]:
    """Busca citas futuras de Stuart solo por coincidencia exacta del correo invitado.

    Devuelve hasta diez citas en el próximo año. Si hay varias, pregunta cuál
    quiere modificar antes de reagendar o cancelar. fecha_original acota a un día.
    """
    _require_access("search", correo_confirmado)
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
                    f"{MONTHS_ES[event_start.month - 1]} a las {_spoken_time(event_start)}"
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
    correo_confirmado: str,
    inicio_original_confirmado: str,
    confirmacion_usuario: bool = False,
) -> dict[str, str]:
    """Mueve la cita elegida tras confirmar explícitamente la cita original y la nueva hora.

    Conserva el mismo evento y sus invitados. Revalida el correo invitado,
    disponibilidad, jornada y duración. No crea una segunda invitación.
    """
    _require_access("reschedule", correo_confirmado)
    email = _require_confirmed_email(correo_confirmado)
    if not confirmacion_usuario:
        raise ValueError(
            "Espera la confirmación explícita del cliente antes de mover la cita."
        )
    now = datetime.now(TIME_ZONE)
    start = _parse_rfc3339(nuevo_inicio)
    if not _is_within_policy(start, now):
        raise ValueError(
            "El nuevo horario debe estar dentro de las próximas dos semanas, en jornada hábil y fuera del almuerzo."
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
    return {
        "estado": "reagendada",
        "evento_id": updated.get("id", evento_id),
        "inicio_anterior": previous_start.isoformat(timespec="minutes"),
        "inicio": start.isoformat(timespec="minutes"),
        "fin": end.isoformat(timespec="minutes"),
        "duracion_minutos": "30",
        "zona_horaria": TIME_ZONE_NAME,
        "invitacion_actualizada_para": email,
    }


@mcp.tool()
def cancelar_reunion(
    evento_id: str,
    correo_confirmado: str,
    inicio_original_confirmado: str,
    confirmacion_usuario: bool = False,
) -> dict[str, str]:
    """Cancela una cita futura de Stuart encontrada por el correo del invitado.

    Primero pide y confirma el correo, busca la cita con buscar_reuniones,
    repite su fecha y hora y espera un sí explícito para cancelar. Revalida
    la coincidencia del invitado y la cita antes de notificar la cancelación.
    """
    _require_access("cancel", correo_confirmado)
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
    return {
        "estado": "cancelada",
        "evento_id": evento_id,
        "inicio_anterior": original_start.isoformat(timespec="minutes"),
        "zona_horaria": TIME_ZONE_NAME,
        "notificacion_enviada_a": email,
    }


if __name__ == "__main__":
    try:
        mcp.run(transport="stdio")
    finally:
        _access.close()
