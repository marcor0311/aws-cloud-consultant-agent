"""Read agent settings and external credentials without importing the backend."""

import os
import re
from pathlib import Path

from dotenv import dotenv_values

ENV_FILE = Path(__file__).resolve().parents[3] / ".env"
AGENT_KEYS = frozenset(
    {
        "GOOGLE_OAUTH_CLIENT_FILE",
        "GOOGLE_OAUTH_TOKEN_FILE",
        "GOOGLE_ACCOUNT_EMAIL",
        "GOOGLE_CALENDAR_ID",
        "CALENDAR_ACCESS_URL",
        "CALENDAR_ACCESS_SERVICE_KEY",
        "CALENDAR_ACCESS_ORIGIN_ID",
        "WORKFLOW_ENABLED",
        "CALENDAR_ASSISTANT_MODE",
        "CALENDAR_MOCK_DB",
        "MOCK_CLOCK_FILE",
        "CALENDAR_ADVISOR_TRANSFER_TIMEOUT_SECONDS",
    }
)


def secrets_directory() -> Path:
    local = dotenv_values(ENV_FILE, interpolate=False)
    configured = os.getenv("CLOUD_CONSULTANT_SECRETS_DIR") or local.get(
        "CLOUD_CONSULTANT_SECRETS_DIR"
    )
    path = (
        Path(configured).expanduser()
        if configured
        else Path.home() / ".config/aws-cloud-consultant-agent/dev"
    )
    if not path.is_absolute():
        raise ValueError("CLOUD_CONSULTANT_SECRETS_DIR debe ser una ruta absoluta.")
    return path


def private_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else secrets_directory() / path


def load_environment() -> None:
    if os.getenv("CALENDAR_ASSISTANT_MODE") == "mock":
        # Every demo setting is supplied explicitly; do not read private credentials.
        return
    local = dotenv_values(ENV_FILE, interpolate=False)
    private = dotenv_values(secrets_directory() / "secrets.env", interpolate=False)
    # Backend mail, database and verification secrets never enter the agent environment.
    for values in (private, local):
        for key, value in values.items():
            if value is not None and (
                key in AGENT_KEYS
                or key.startswith("LIVEKIT_")
                or (values is private and key == "CALENDAR_ADVISOR_TRANSFER_E164")
            ):
                os.environ.setdefault(key, value)
    for key, default in {
        "GOOGLE_OAUTH_CLIENT_FILE": "google/oauth-client.json",
        "GOOGLE_OAUTH_TOKEN_FILE": "google/calendar-token.json",
    }.items():
        os.environ[key] = str(private_path(os.getenv(key) or default))


def advisor_transfer_settings() -> tuple[str, int]:
    """The destination comes only from the process or private secrets.env."""
    destination = os.getenv("CALENDAR_ADVISOR_TRANSFER_E164", "").strip()
    if not re.fullmatch(r"\+[1-9][0-9]{1,14}", destination):
        raise ValueError("Destino privado de transferencia no configurado en E.164.")
    timeout = int(os.getenv("CALENDAR_ADVISOR_TRANSFER_TIMEOUT_SECONDS", "10"))
    if not 1 <= timeout <= 120:
        raise ValueError(
            "El timeout de transferencia debe estar entre 1 y 120 segundos."
        )
    return destination, timeout


def require_inference_enabled() -> None:
    """Require explicit opt-in before starting a session that spends cloud credits."""
    if os.getenv("LIVEKIT_INFERENCE_ENABLED") != "1":
        raise RuntimeError(
            "Inferencia LiveKit bloqueada para proteger los créditos. "
            "Solo para una prueba real autorizada, ejecuta con "
            "LIVEKIT_INFERENCE_ENABLED=1."
        )
