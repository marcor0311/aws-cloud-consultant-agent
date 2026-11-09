"""Slack callbacks are authenticated before touching PostgreSQL; no live poll is sent here."""

import os
import time

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response

from app.api.dependencies import get_opening_runtime
from app.integrations.errors import ProviderError
from app.integrations.slack_board import SlackBoardActions, verify_slack_signature
from app.persistence.locking import Busy

router = APIRouter(tags=["Junta directiva"])


@router.post("/board/slack/actions")
async def board_action(request: Request, tasks: BackgroundTasks):
    secret = os.getenv("SLACK_SIGNING_SECRET", "")
    if not secret:
        raise HTTPException(503, "La recepción de votos Slack no está configurada.")
    raw = await request.body()
    timestamp = request.headers.get("x-slack-request-timestamp", "")
    signature = request.headers.get("x-slack-signature", "")
    try:
        verify_slack_signature(raw, timestamp, signature, secret, time.time())
    except (ValueError, TypeError):
        raise HTTPException(403, "Solicitud Slack no autenticada.") from None
    runtime = get_opening_runtime()
    try:
        ballot = SlackBoardActions(runtime.board, secret, clock=time.time).handle(
            raw, timestamp, signature
        )
    except (ValueError, TypeError, KeyError):
        raise HTTPException(
            400, "El voto no corresponde a una votación abierta y autorizada."
        ) from None
    except Busy:
        raise HTTPException(503, "Otro voto se está registrando; reintentá.") from None

    def update_message():
        try:
            runtime.board.sync_poll(ballot["id"])
        except (ProviderError, ValueError):
            # The durable vote already committed; a UI refresh cannot erase it.
            pass

    tasks.add_task(update_message)
    return Response(status_code=200)
