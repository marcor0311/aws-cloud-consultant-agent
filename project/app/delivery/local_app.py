"""Standalone loopback demo; the main backend also registers these routes."""

from app.delivery.api import router
from fastapi import FastAPI

app = FastAPI(title="Entrega 1 - Ingeniería e informe", version="0.1.0")
app.include_router(router, prefix="/api")
