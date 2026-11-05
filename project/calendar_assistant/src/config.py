"""Read only agent settings from the shared project/.env configuration."""

import os
from pathlib import Path

from dotenv import dotenv_values

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
AGENT_KEYS = frozenset(
    {
        "GOOGLE_OAUTH_CLIENT_FILE",
        "GOOGLE_OAUTH_TOKEN_FILE",
        "GOOGLE_ACCOUNT_EMAIL",
        "GOOGLE_CALENDAR_ID",
        "CALENDAR_ACCESS_URL",
        "CALENDAR_ACCESS_SERVICE_KEY",
        "CALENDAR_ACCESS_ORIGIN_ID",
    }
)


def load_environment() -> None:
    # Backend mail, whitelist and verification secrets are not loaded by the agent.
    for key, value in dotenv_values(ENV_FILE, interpolate=False).items():
        if value is not None and (key in AGENT_KEYS or key.startswith("LIVEKIT_")):
            os.environ.setdefault(key, value)
