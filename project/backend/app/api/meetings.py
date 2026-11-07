"""Authenticated ingestion and manager operations; external events are queued durably."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.api.dependencies import (
    get_access_service,
    get_call_receipt_key,
    get_runtime,
    require_service,
)
from app.verification.service import CalendarAccessService
from app.workflow.receipts import accept_call_receipt
from app.workflow.runtime import WorkflowRuntime

router = APIRouter(tags=["Flujo de reuniones"])
Runtime = Annotated[WorkflowRuntime, Depends(get_runtime)]


class MeetingEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(min_length=20, max_length=160)
    client_code: str = Field(pattern=r"^[A-Z]{4}-[0-9]{4}$")
    email: str = Field(max_length=254)
    calendar_id: str = Field(min_length=1, max_length=254)
    calendar_event_id: str = Field(min_length=1, max_length=256)
    operation: Literal["scheduled", "rescheduled", "cancelled"]
    version: str = Field(max_length=256)
    started_at: AwareDatetime | None = None
    completed_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def valid_interval(self):
        if bool(self.started_at) != bool(self.completed_at):
            raise ValueError("Se requieren ambos límites del intervalo.")
        if (
            self.started_at
            and not 0 <= (self.completed_at - self.started_at).total_seconds() <= 3600
        ):
            raise ValueError("Intervalo de agenda inválido.")
        return self


@router.post("/calendar-access/meeting", dependencies=[Depends(require_service)])
def register_meeting(
    payload: MeetingEvent,
    runtime: Runtime,
    access: Annotated[CalendarAccessService, Depends(get_access_service)],
):
    authorization = access.authorize(payload.session_id, payload.email)
    client = access.clients.lookup_code(payload.client_code)
    if (
        authorization.get("status") != "authorized"
        or not client
        or not client.enabled
        or client.company_email != authorization.get("email")
    ):
        raise HTTPException(403, "Se requiere la verificación vigente del cliente.")
    data = payload.model_dump(
        mode="json", exclude={"session_id", "email", "client_code"}
    )
    return runtime.register_meeting(data, client.client_id)


@router.post("/calendar-access/call-ended", dependencies=[Depends(require_service)])
def register_closed_call(
    receipt: dict,
    runtime: Runtime,
    access: Annotated[CalendarAccessService, Depends(get_access_service)],
    key: Annotated[str, Depends(get_call_receipt_key)],
):
    # The signed tool receipt survives revocation of the conversational OTP session.
    try:
        return accept_call_receipt(
            runtime,
            receipt,
            key,
            access.clients.lookup_code,
        )
    except (ValueError, KeyError, TypeError):
        raise HTTPException(400, "El recibo de cierre no es válido.") from None
