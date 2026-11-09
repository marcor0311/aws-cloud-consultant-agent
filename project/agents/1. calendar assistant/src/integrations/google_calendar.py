"""Construct the authorized Google Calendar client and refresh its token."""

import os
import tempfile
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from src.config import private_path

SCOPES = [
    "https://www.googleapis.com/auth/calendar.freebusy",
    "https://www.googleapis.com/auth/calendar.events.owned",
]


def _configured_path(variable: str, default_name: str) -> Path:
    return private_path(os.getenv(variable) or default_name)


def _calendar_ids(_service) -> list[str]:
    calendar_id = os.getenv("GOOGLE_CALENDAR_ID", "primary")
    return ["primary" if calendar_id == "all" else calendar_id]


def _save_credentials(credentials: Credentials, token_file: Path) -> None:
    token_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(dir=token_file.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(credentials.to_json())
        os.replace(temporary, token_file)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _calendar_service():
    if os.getenv("CALENDAR_ASSISTANT_MODE") == "mock":
        from src.integrations.mock_calendar import MockCalendar

        return MockCalendar(os.environ["CALENDAR_MOCK_DB"])
    token_file = _configured_path(
        "GOOGLE_OAUTH_TOKEN_FILE", "google/calendar-token.json"
    )
    if not token_file.is_file():
        raise RuntimeError(
            "Google Calendar aún no está autorizado. Ejecuta `uv run "
            "python -m src.integrations.google_oauth` y autoriza la cuenta configurada."
        )

    credentials = Credentials.from_authorized_user_file(str(token_file), SCOPES)
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        _save_credentials(credentials, token_file)
    if not credentials.valid:
        raise RuntimeError(
            "La autorización de Google expiró. Vuelve a ejecutar "
            "`uv run python -m src.integrations.google_oauth`."
        )
    return build("calendar", "v3", credentials=credentials, cache_discovery=False)
