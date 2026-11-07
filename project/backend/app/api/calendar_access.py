"""Internal HTTP endpoints; business behavior lives in the verification service."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import get_access_service, require_service
from app.verification.schemas import (
    AuthorizeOperation,
    ChallengePayload,
    SessionPayload,
    StartVerification,
    VerifyCode,
)
from app.verification.service import CalendarAccessService

router = APIRouter(prefix="/calendar-access", tags=["Acceso al calendario"])

AccessService = Annotated[CalendarAccessService, Depends(get_access_service)]


@router.post("/start", dependencies=[Depends(require_service)])
def start(payload: StartVerification, service: AccessService):
    return service.start(payload.session_id, payload.client_code, payload.origin_id)


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
