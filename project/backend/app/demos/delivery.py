"""Standalone loopback demo; the main backend also registers these routes."""

from fastapi import FastAPI

from app.api.delivery import router

app = FastAPI(title="Entrega 1 - Ingeniería e informe", version="0.1.0")
app.include_router(router, prefix="/api")
