"""Create a separate Meet/Events/PubSub token without modifying Calendar or Gmail tokens."""

import os

from google_auth_oauthlib.flow import InstalledAppFlow

from app.core.config import load_environment, private_path

SCOPES = [
    "https://www.googleapis.com/auth/meetings.space.readonly",
    "https://www.googleapis.com/auth/calendar.events.readonly",
    "https://www.googleapis.com/auth/pubsub",
]


def main():
    load_environment()
    client_file = os.getenv("WORKFLOW_GOOGLE_CLIENT_FILE", "")
    token_file = os.getenv("WORKFLOW_GOOGLE_TOKEN_FILE", "")
    if not client_file or not token_file:
        raise SystemExit(
            "Configurar WORKFLOW_GOOGLE_CLIENT_FILE y WORKFLOW_GOOGLE_TOKEN_FILE."
        )
    target = private_path(token_file)
    if target.exists():
        raise SystemExit(
            "El token ya existe; no se reemplaza una autorización existente."
        )
    credentials = InstalledAppFlow.from_client_secrets_file(
        str(private_path(client_file)), SCOPES
    ).run_local_server(port=0)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as output:
        output.write(credentials.to_json())
    print("Autorización del flujo guardada; tokens Calendar y Gmail conservados.")


if __name__ == "__main__":
    main()
