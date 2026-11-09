"""Authorize the local calendar MCP server to access the configured Google account."""

import os
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

from src.config import load_environment, private_path
from src.integrations.google_calendar import SCOPES, _save_credentials

load_environment()


def _configured_path(variable: str, default_name: str) -> Path:
    return private_path(os.getenv(variable) or default_name)


def main() -> None:
    client_file = _configured_path(
        "GOOGLE_OAUTH_CLIENT_FILE", "google/oauth-client.json"
    )
    token_file = _configured_path(
        "GOOGLE_OAUTH_TOKEN_FILE", "google/calendar-token.json"
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
    _save_credentials(credentials, token_file)
    print(f"Autorización guardada localmente en {token_file.name}.")


if __name__ == "__main__":
    main()
