"""Authorize Gmail sending locally, without modifying the Calendar token."""

from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

from app.config import load_environment
from app.services.gmail_mailer import (
    GMAIL_SEND_SCOPE,
    PROJECT_DIR,
    GmailSettings,
    configured_path,
    save_credentials,
)


def authorize() -> Path:
    load_environment()
    settings = GmailSettings.from_environment()
    client_file = configured_path(
        "CALENDAR_GMAIL_CLIENT_FILE",
        "calendar_assistant/secrets/google_oauth_client.json",
    )
    if not client_file.is_file():
        raise RuntimeError("No encuentro el cliente OAuth configurado para Gmail.")
    calendar_token = (
        PROJECT_DIR / "calendar_assistant/secrets/google_calendar_token.json"
    )
    if settings.token_file.resolve() in {
        client_file.resolve(),
        calendar_token.resolve(),
    }:
        raise RuntimeError("Configura un archivo de token separado para Gmail.")
    flow = InstalledAppFlow.from_client_secrets_file(
        str(client_file), scopes=[GMAIL_SEND_SCOPE], autogenerate_code_verifier=True
    )
    credentials = flow.run_local_server(
        host="127.0.0.1",
        port=0,
        access_type="offline",
        prompt="consent",
        login_hint=settings.sender,
        timeout_seconds=300,
        authorization_prompt_message=(
            "Autoriza en el navegador únicamente el envío de correo con tu cuenta configurada.\n{url}"
        ),
        success_message="Autorización de envío completada. Puedes volver al proyecto.",
    )
    granted = credentials.granted_scopes or credentials.scopes or []
    if GMAIL_SEND_SCOPE not in granted or not credentials.refresh_token:
        raise RuntimeError(
            "No se concedió el permiso de envío con acceso sin conexión."
        )
    # A dedicated backend token avoids sharing the Calendar authorization file.
    save_credentials(credentials, settings.token_file)
    return settings.token_file


def main():
    try:
        authorize()
    except Exception:
        raise SystemExit(
            "No se completó la autorización de Gmail. Revisa el consentimiento y vuelve a intentarlo."
        ) from None
    print("Gmail autorizado. Token guardado en secrets/ con permisos restringidos.")


if __name__ == "__main__":
    main()
