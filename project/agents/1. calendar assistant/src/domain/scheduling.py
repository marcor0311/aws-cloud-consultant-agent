"""Meeting policy, date parsing and spoken availability; no external services."""

import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import dateparser
from text_to_num import alpha2digit

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
    hours = (
        "doce",
        "una",
        "dos",
        "tres",
        "cuatro",
        "cinco",
        "seis",
        "siete",
        "ocho",
        "nueve",
        "diez",
        "once",
    )
    clock = hours[hour % 12]
    if local_time.minute == 0:
        return clock
    if local_time.minute == 30:
        return f"{clock} y media"
    if local_time.minute == 15:
        return f"{clock} y cuarto"
    # Legacy invitations can contain minutes outside the current half-hour slots.
    small_numbers = (
        "cero",
        "uno",
        "dos",
        "tres",
        "cuatro",
        "cinco",
        "seis",
        "siete",
        "ocho",
        "nueve",
        "diez",
        "once",
        "doce",
        "trece",
        "catorce",
        "quince",
        "dieciséis",
        "diecisiete",
        "dieciocho",
        "diecinueve",
        "veinte",
        "veintiuno",
        "veintidós",
        "veintitrés",
        "veinticuatro",
        "veinticinco",
        "veintiséis",
        "veintisiete",
        "veintiocho",
        "veintinueve",
    )
    minute = local_time.minute
    if minute < 30:
        minutes = small_numbers[minute]
    else:
        minutes = {3: "treinta", 4: "cuarenta", 5: "cincuenta"}[minute // 10]
        if minute % 10:
            minutes += f" y {small_numbers[minute % 10]}"
    return f"{clock} y {minutes}"


def _time_phrase(
    value: datetime, *, preposition: str = "a", period: bool = True
) -> str:
    local_time = value.astimezone(TIME_ZONE)
    article = "la" if local_time.hour % 12 == 1 else "las"
    clock = _spoken_time(local_time) if period else _clock_only(local_time)
    return f"{preposition} {article} {clock}"


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
        # Advertise possible START times, not the end of the last appointment.
        end -= MEETING_DURATION
        if start == end:
            formatted.append(_time_phrase(start))
        else:
            start_period = "de la mañana" if start.hour < 12 else "de la tarde"
            end_period = "de la mañana" if end.hour < 12 else "de la tarde"
            if start_period == end_period:
                formatted.append(
                    f"{_time_phrase(start, preposition='de', period=False)} "
                    f"{_time_phrase(end, period=False)} {end_period}"
                )
            else:
                formatted.append(
                    f"{_time_phrase(start, preposition='de')} {_time_phrase(end)}"
                )
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
    is_pm = bool(re.search(r"\b(p\s*m|de la tarde|de la noche)\b", normalized))
    is_am = bool(re.search(r"\b(a\s*m|de la mañana)\b", normalized))
    normalized = re.sub(
        r"\b(a las|a la|las|la|de la tarde|de la noche|de la mañana|p\s*m|a\s*m)\b",
        " ",
        normalized,
    )
    normalized = re.sub(r"\ben punto\b", " ", normalized)
    normalized = re.sub(r"\s+y\s+media\b", ":30", normalized)
    normalized = re.sub(r"\s+y\s+(\d{1,2})\b", r":\1", normalized)
    # Reject unparsed minutes/seconds instead of silently using just the hour.
    match = re.fullmatch(r"\s*(\d{1,2})(?::(\d{1,2}))?\s*", normalized)
    if not match:
        raise ValueError(
            "Solo se permiten horas en punto o y media; pide que aclare la hora."
        )

    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    if not 0 <= hour <= 23 or minute not in (0, 30):
        raise ValueError(
            "Solo se permiten horas en punto o y media, con minutos 00 o 30."
        )
    if is_pm and not is_am and 1 <= hour <= 11:
        hour += 12
    elif is_am and not is_pm and hour == 12:
        hour = 0
    elif not is_pm and not is_am and 1 <= hour <= 7:
        # In the stated 08:00-17:00 work window, these hours mean afternoon.
        hour += 12
    return time(hour, minute)
