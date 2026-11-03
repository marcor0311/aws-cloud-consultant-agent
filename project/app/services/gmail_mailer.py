"""Send verification messages with Gmail OAuth; no mailbox read permission."""

import base64
import json
import os
import tempfile
import threading
from dataclasses import dataclass
from functools import partial
from pathlib import Path

import httpx
from app.models.calendar_access import normalize_email
from app.services.calendar_mailer import build_code_message
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
PROJECT_DIR = Path(__file__).resolve().parents[2]
_send_lock = threading.Lock()


def configured_path(variable: str, default: str) -> Path:
    path = Path(os.getenv(variable, default)).expanduser()
    return path if path.is_absolute() else PROJECT_DIR / path


def save_credentials(credentials: Credentials, token_file: Path) -> None:
    token_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=token_file.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(credentials.to_json())
        temporary.chmod(0o600)
        os.replace(temporary, token_file)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


@dataclass(frozen=True)
class GmailSettings:
    sender: str
    token_file: Path

    def __post_init__(self):
        object.__setattr__(self, "sender", normalize_email(self.sender))

    @classmethod
    def from_environment(cls):
        return cls(
            sender=os.getenv("GOOGLE_ACCOUNT_EMAIL", ""),
            token_file=configured_path(
                "CALENDAR_GMAIL_TOKEN_FILE", "secrets/gmail_token.json"
            ),
        )


class GmailMailer:
    def __init__(self, settings: GmailSettings):
        self.settings = settings

    def _credentials(self) -> Credentials:
        try:
            info = json.loads(self.settings.token_file.read_text(encoding="utf-8"))
            # Do not relabel a Calendar-only token by supplying different scopes.
            if not isinstance(info, dict) or GMAIL_SEND_SCOPE not in info.get(
                "scopes", []
            ):
                raise ValueError("Falta autorización de envío.")
            if info.get("token_uri") != "https://oauth2.googleapis.com/token":
                raise ValueError("El endpoint de autorización no es de Google.")
            credentials = Credentials.from_authorized_user_info(info)
            if credentials.expired and credentials.refresh_token:
                credentials.refresh(partial(Request(), timeout=10))
                save_credentials(credentials, self.settings.token_file)
            if not credentials.valid or not credentials.has_scopes([GMAIL_SEND_SCOPE]):
                raise ValueError("La autorización no es válida.")
            return credentials
        except (OSError, ValueError, TypeError, GoogleAuthError):
            raise RuntimeError(
                "Gmail no está autorizado. Ejecuta python -m app.authorize_gmail desde project/."
            ) from None

    def send_code(self, email: str, name: str, code: str, minutes: int) -> None:
        recipient = normalize_email(email)
        message = build_code_message(self.settings.sender, "", recipient, code, minutes)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        with _send_lock:
            credentials = self._credentials()
            try:
                response = httpx.post(
                    "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
                    headers={"Authorization": f"Bearer {credentials.token}"},
                    json={"raw": raw},
                    timeout=10,
                    follow_redirects=False,
                )
                response.raise_for_status()
                result = response.json()
                if (
                    not isinstance(result, dict)
                    or not isinstance(result.get("id"), str)
                    or not result["id"]
                ):
                    raise ValueError("Gmail no confirmó la aceptación.")
            except (httpx.HTTPError, ValueError, TypeError):
                # Never retry an ambiguous send automatically or expose the MIME/token.
                raise RuntimeError(
                    "Gmail no confirmó el envío. Intente más tarde."
                ) from None
