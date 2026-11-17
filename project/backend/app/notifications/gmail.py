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
from google.auth.exceptions import GoogleAuthError, RefreshError, TransportError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from app.core.config import private_path
from app.core.validation import normalize_email
from app.integrations.errors import ConfigurationError, ProviderError
from app.notifications.message import build_code_message

GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"

_send_lock = threading.Lock()


def configured_path(variable: str, default: str) -> Path:
    return private_path(os.getenv(variable) or default)


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
                "CALENDAR_GMAIL_TOKEN_FILE", "google/gmail-token.json"
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
        except RefreshError as error:
            payload = next((arg for arg in error.args if isinstance(arg, dict)), {})
            code = payload.get("error")
            reasons = {
                "invalid_grant": "Google rechazó la autorización de renovación "
                "(invalid_grant); puede haber vencido o sido revocada.",
                "invalid_client": "Google rechazó el cliente OAuth (invalid_client). "
                "Revisá las credenciales del cliente con el que se emitió el token.",
                "invalid_scope": "Google rechazó los permisos de envío (invalid_scope).",
                "unauthorized_client": "El cliente OAuth no está autorizado "
                "para renovar el acceso (unauthorized_client).",
                "temporarily_unavailable": "El servidor OAuth de Google no está "
                "disponible temporalmente (temporarily_unavailable).",
                "server_error": "El servidor OAuth de Google falló (server_error).",
            }
            code = code if isinstance(code, str) else ""
            reason = reasons.get(code, "Google rechazó renovar el acceso a Gmail.")
            if error.retryable or code in {"temporarily_unavailable", "server_error"}:
                raise ProviderError(
                    "gmail_oauth_refresh_unavailable",
                    detail=f"Gmail OAuth: {reason} Intentá más tarde; no se envió el OTP.",
                ) from None
            raise ConfigurationError(
                "gmail_oauth_refresh_rejected",
                detail=f"Gmail OAuth: {reason} Ejecutá make gmail-auth desde la raíz "
                "y completá el consentimiento. Gmail tiene su propio token; "
                "autorizar Calendar no renueva esta credencial. No se envió el OTP.",
            ) from None
        except TransportError:
            raise ProviderError(
                "gmail_oauth_transport_error",
                detail="Gmail OAuth: no se pudo contactar el servidor para renovar "
                "el acceso. Revisá la conexión, DNS o proxy. No se envió el OTP.",
            ) from None
        except (OSError, ValueError, TypeError, GoogleAuthError):
            raise ConfigurationError(
                "gmail_credentials_unavailable",
                detail="Gmail: no se pudo cargar, validar o guardar la autorización. "
                "Revisá CALENDAR_GMAIL_TOKEN_FILE y sus permisos; para autorizar "
                "el envío ejecutá make gmail-auth desde la raíz del repositorio.",
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
