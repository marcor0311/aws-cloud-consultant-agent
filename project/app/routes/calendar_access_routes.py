"""Internal routes for the authenticated calling service."""

import hmac
import os
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.models.calendar_access import (
    AuthorizeOperation,
    ChallengePayload,
    SessionPayload,
    StartVerification,
    VerifyCode,
)
from app.services.calendar_access import CalendarAccessService
from app.services.calendar_mailer import SMTPMailer, SMTPSettings
from app.services.calendar_whitelist import configured_whitelist
from app.services.gmail_mailer import GmailMailer, GmailSettings

router = APIRouter(prefix="/calendar-access", tags=["Acceso al calendario"])
bearer = HTTPBearer(auto_error=False)
PROJECT_DIR = Path(__file__).resolve().parents[2]


def _authenticate(credentials: HTTPAuthorizationCredentials | None):
    service_key = os.getenv("CALENDAR_ACCESS_SERVICE_KEY", "")
    if len(service_key) < 32:
        raise HTTPException(503, "El acceso al calendario no está configurado.")
    if not credentials or not hmac.compare_digest(
        credentials.credentials.encode(), service_key.encode()
    ):
        raise HTTPException(
            401, "Credencial inválida.", headers={"WWW-Authenticate": "Bearer"}
        )


def require_service(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
):
    _authenticate(credentials)


class EnvironmentMailer:
    """Load the selected provider only after checking the whitelist."""

    def send_code(self, email: str, name: str, code: str, minutes: int):
        provider = os.getenv("CALENDAR_MAIL_PROVIDER", "smtp").strip().lower()
        if provider == "gmail":
            GmailMailer(GmailSettings.from_environment()).send_code(
                email, name, code, minutes
            )
            return
        if provider != "smtp":
            raise ValueError("El proveedor de correo no es válido.")
        settings = SMTPSettings(
            host=os.getenv("CALENDAR_SMTP_HOST", ""),
            port=int(os.getenv("CALENDAR_SMTP_PORT", "587")),
            username=os.getenv("CALENDAR_SMTP_USERNAME", ""),
            password=os.getenv("CALENDAR_SMTP_PASSWORD", ""),
            sender=os.getenv("CALENDAR_SMTP_FROM", ""),
            sender_name=os.getenv("CALENDAR_SMTP_SENDER_NAME", ""),
            security=os.getenv("CALENDAR_SMTP_SECURITY", "starttls"),
        )
        SMTPMailer(settings).send_code(email, name, code, minutes)


@lru_cache(maxsize=1)
def get_access_service() -> CalendarAccessService:
    secret = os.getenv("CALENDAR_ACCESS_CODE_SECRET", "")
    if secret == os.getenv("CALENDAR_ACCESS_SERVICE_KEY", ""):
        raise HTTPException(503, "Configura claves independientes para el acceso.")
    database = Path(os.getenv("CALENDAR_ACCESS_DB", "data/calendar-access.sqlite3"))
    if not database.is_absolute():
        database = PROJECT_DIR / database
    try:
        return CalendarAccessService(
            database, secret, EnvironmentMailer(), configured_whitelist()
        )
    except (ValueError, OSError, sqlite3.Error):
        raise HTTPException(
            503, "El acceso al calendario no está disponible."
        ) from None


AccessService = Annotated[CalendarAccessService, Depends(get_access_service)]


@router.post("/start", dependencies=[Depends(require_service)])
def start(payload: StartVerification, service: AccessService):
    return service.start(payload.session_id, payload.email, payload.origin_id)


@router.post("/verify", dependencies=[Depends(require_service)])
def verify(payload: VerifyCode, service: AccessService):
    return service.verify(
        payload.session_id, payload.challenge_id, payload.code.get_secret_value()
    )


@router.post("/resend", dependencies=[Depends(require_service)])
def resend(payload: ChallengePayload, service: AccessService):
    return service.resend(payload.session_id, payload.challenge_id)


@router.post("/authorize", dependencies=[Depends(require_service)])
def authorize(payload: AuthorizeOperation, service: AccessService):
    return service.authorize(payload.session_id, payload.email)


@router.post("/close", dependencies=[Depends(require_service)])
def close(payload: SessionPayload, service: AccessService):
    return service.close(payload.session_id)
