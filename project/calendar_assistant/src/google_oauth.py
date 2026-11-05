"""Authorize the local calendar MCP server to access the configured Google account."""

import os
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

try:
    from .config import load_environment
except ImportError:  # Executed directly by the OAuth setup command.
    from config import load_environment

PROJECT_DIR = Path(__file__).resolve().parents[1]
load_environment()

SCOPES = [
    "https://www.googleapis.com/auth/calendar.freebusy",
    "https://www.googleapis.com/auth/calendar.events.owned",
]


def _configured_path(variable: str, default_name: str) -> Path:
    configured = Path(os.getenv(variable, default_name)).expanduser()
    return configured if configured.is_absolute() else PROJECT_DIR / configured


def main() -> None:
    client_file = _configured_path(
        "GOOGLE_OAUTH_CLIENT_FILE", "secrets/google_oauth_client.json"
    )
    token_file = _configured_path(
        "GOOGLE_OAUTH_TOKEN_FILE", "secrets/google_calendar_token.json"
    )
    if not client_file.is_file():
        raise SystemExit(
            f"No encuentro {client_file}. Descarga el cliente OAuth de Google "
            "y guárdalo en esa ubicación."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(client_file), SCOPES)
    credentials = flow.run_local_server(
        host="127.0.0.1",
        port=0,
        access_type="offline",
        prompt="consent",
    )
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(credentials.to_json(), encoding="utf-8")
    token_file.chmod(0o600)
    print(f"Autorización guardada localmente en {token_file.name}.")


if __name__ == "__main__":
    main()
