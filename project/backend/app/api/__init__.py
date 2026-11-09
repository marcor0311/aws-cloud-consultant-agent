"""Assemble the existing HTTP routers without starting any background process."""

from fastapi import APIRouter

from app.api import board, calendar_access, meetings, webhooks, workflow

router = APIRouter()
for feature in (calendar_access, meetings, webhooks, workflow, board):
    router.include_router(feature.router)
