"""Read agent settings and external credentials without importing the backend."""

import os
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
            if value is not None and (key in AGENT_KEYS or key.startswith("LIVEKIT_")):
                os.environ.setdefault(key, value)
    for key, default in {
        "GOOGLE_OAUTH_CLIENT_FILE": "google/oauth-client.json",
        "GOOGLE_OAUTH_TOKEN_FILE": "google/calendar-token.json",
    }.items():
        os.environ[key] = str(private_path(os.getenv(key) or default))


def require_inference_enabled() -> None:
    """Require explicit opt-in before starting a session that spends cloud credits."""
    if os.getenv("LIVEKIT_INFERENCE_ENABLED") != "1":
        raise RuntimeError(
            "Inferencia LiveKit bloqueada para proteger los créditos. "
            "Solo para una prueba real autorizada, ejecuta con "
            "LIVEKIT_INFERENCE_ENABLED=1."
        )
