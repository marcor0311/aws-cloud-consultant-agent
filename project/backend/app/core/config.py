"""Local configuration and external private state, independent of the caller directory."""

import os
from pathlib import Path

from dotenv import dotenv_values

PROJECT_DIR = Path(__file__).resolve().parents[3]
BACKEND_DIR = PROJECT_DIR / "backend"
REFERENCE_DIR = PROJECT_DIR.parent / "references"
ENV_FILE = PROJECT_DIR / ".env"
DEFAULT_SECRETS_DIR = Path.home() / ".config/aws-cloud-consultant-agent/dev"
SECRET_FILES = {
    "GOOGLE_OAUTH_CLIENT_FILE": "google/oauth-client.json",
    "GOOGLE_OAUTH_TOKEN_FILE": "google/calendar-token.json",
    "CALENDAR_GMAIL_CLIENT_FILE": "google/oauth-client.json",
    "CALENDAR_GMAIL_TOKEN_FILE": "google/gmail-token.json",
    "WORKFLOW_GOOGLE_CLIENT_FILE": "google/oauth-client.json",
    "WORKFLOW_GOOGLE_TOKEN_FILE": "google/workflow-token.json",
}


def secrets_directory() -> Path:
    local = dotenv_values(ENV_FILE, interpolate=False)
    configured = os.getenv("CLOUD_CONSULTANT_SECRETS_DIR") or local.get(
        "CLOUD_CONSULTANT_SECRETS_DIR"
    )
    path = Path(configured).expanduser() if configured else DEFAULT_SECRETS_DIR
    if not path.is_absolute():
        raise ValueError("CLOUD_CONSULTANT_SECRETS_DIR debe ser una ruta absoluta.")
    return path


def private_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else secrets_directory() / path


def load_environment() -> None:
    # Explicit process values win over private values and repository configuration.
    # Disable interpolation: passwords and tokens may contain literal '$' characters.
    local = dotenv_values(ENV_FILE, interpolate=False)
    private = dotenv_values(secrets_directory() / "secrets.env", interpolate=False)
    for values in (private, local):
        for key, value in values.items():
            if value is not None:
                os.environ.setdefault(key, value)
    for key, default in SECRET_FILES.items():
        os.environ[key] = str(private_path(os.getenv(key) or default))


def project_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else PROJECT_DIR / path
