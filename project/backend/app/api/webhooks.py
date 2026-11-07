"""Authenticated ingestion and manager operations; external events are queued durably."""

import hashlib
import hmac
import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token

from app.api.dependencies import (
    bearer,
    get_runtime,
    require_transcript_capture,
)
from app.workflow.calendar_sync import CalendarSync
from app.workflow.runtime import WorkflowRuntime
from app.workflow.settings import WorkflowSettings

router = APIRouter(tags=["Flujo de reuniones"])
Runtime = Annotated[WorkflowRuntime, Depends(get_runtime)]


@router.post(
    "/workflow/events/transcript",
    dependencies=[Depends(require_transcript_capture)],
    status_code=202,
)
async def captured_transcript(request: Request, runtime: Runtime):
    from app.workflow.transcripts import receive_capture

    raw = await request.body()
    if len(raw) > 1_000_000:
        raise HTTPException(413, "El transcript excede el tamaño admitido.")
    try:
        return receive_capture(runtime, json.loads(raw))
    except (ValueError, TypeError, KeyError):
        raise HTTPException(
            400, "Captura inválida o ID reutilizado con otros datos."
        ) from None


@router.post("/workflow/events/calendar", status_code=202)
def calendar_event(request: Request, runtime: Runtime):
    try:
        return CalendarSync(runtime).receive(request.headers)
    except ValueError:
        raise HTTPException(403, "Notificación de Calendar no autorizada.") from None


def require_pubsub(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
):
    settings = WorkflowSettings.from_environment()
    if not settings.push_audience or not settings.push_service_account:
        raise HTTPException(503, "La autenticación Pub/Sub no está configurada.")
    if not credentials:
        raise HTTPException(401, "Falta la identidad de Pub/Sub.")
    try:
        claims = id_token.verify_oauth2_token(
            credentials.credentials, GoogleRequest(), settings.push_audience
        )
    except Exception:
        raise HTTPException(401, "Identidad Pub/Sub inválida.") from None
    if (
        claims.get("email") != settings.push_service_account
        or claims.get("email_verified") is not True
    ):
        raise HTTPException(403, "La cuenta Pub/Sub no está autorizada.")


@router.post(
    "/workflow/events/meet", dependencies=[Depends(require_pubsub)], status_code=202
)
async def meet_event(request: Request, runtime: Runtime):
    raw = await request.body()
    if len(raw) > 1_100_000:
        raise HTTPException(413, "Evento demasiado grande.")
    try:
        payload = json.loads(raw)
        return runtime.receive_message(payload["message"])
    except (ValueError, KeyError, TypeError):
        raise HTTPException(400, "Evento Pub/Sub inválido.") from None


@router.post("/workflow/events/github", status_code=202)
async def github_event(request: Request, runtime: Runtime):
    settings = runtime.settings
    if len(settings.github_secret) < 32:
        raise HTTPException(503, "El webhook GitHub no está configurado.")
    raw = await request.body()
    if len(raw) > 1_100_000:
        raise HTTPException(413, "Evento demasiado grande.")
    expected = (
        "sha256="
        + hmac.new(settings.github_secret.encode(), raw, hashlib.sha256).hexdigest()
    )
    if not hmac.compare_digest(
        request.headers.get("x-hub-signature-256", ""), expected
    ):
        raise HTTPException(401, "Firma GitHub inválida.")
    delivery = request.headers.get("x-github-delivery", "")
    kind = request.headers.get("x-github-event", "")
    if not delivery or len(delivery) > 150:
        raise HTTPException(400, "Falta ID de entrega.")
    if kind not in {"issues", "pull_request"}:
        return {"status": "ignored"}
    try:
        body = json.loads(raw)
        repository = body["repository"]["full_name"]
        issue = body["issue" if kind == "issues" else "pull_request"]
        url = issue["html_url"]
    except (ValueError, KeyError, TypeError):
        raise HTTPException(400, "Evento GitHub inválido.") from None
    if repository not in settings.github_repositories:
        raise HTTPException(403, "Repositorio no autorizado.")
    return runtime.process.observe_github(
        delivery,
        url,
        kind,
        body.get("action"),
        issue.get("created_at"),
        issue.get("closed_at"),
        body.get("action") == "closed"
        and any(
            label.get("name") == "requiere-ajustes" for label in issue.get("labels", [])
        ),
    )
