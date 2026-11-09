"""Local HTTP entry point exposing only the Calendar callback to a dev tunnel."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.dependencies import clear_runtime
from app.api.webhooks import calendar_event
from app.core.config import load_environment

load_environment()


@asynccontextmanager
async def lifespan(_app):
    try:
        yield
    finally:
        clear_runtime()


app = FastAPI(
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    redirect_slashes=False,
)
app.add_api_route(
    "/api/workflow/events/calendar",
    calendar_event,
    methods=["POST"],
    status_code=202,
)
