"""Opt-in local stand-in for the external whitelist; never loaded by app.main.

Run separately with --host 127.0.0.1 for manual tests only.
"""

import hmac
import os
from pathlib import Path
from typing import Annotated

from app.models.calendar_access import EmailPayload, normalize_email
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
app = FastAPI(title="Whitelist local de prueba", docs_url=None, redoc_url=None)
bearer = HTTPBearer(auto_error=False)


@app.post("/lookup")
def lookup(
    payload: EmailPayload,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
):
    key = os.getenv("CALENDAR_WHITELIST_API_KEY", "")
    email = os.getenv("CALENDAR_DEMO_EMAIL", "")
    if os.getenv("CALENDAR_DEMO_MODE") != "true" or len(key) < 32 or not email:
        raise HTTPException(503, "La whitelist de prueba no está habilitada.")
    if not credentials or not hmac.compare_digest(
        credentials.credentials.encode(), key.encode()
    ):
        raise HTTPException(401, "Credencial inválida.")
    if payload.email != normalize_email(email):
        return {"registered": False}
    return {"registered": True, "enabled": True, "name": "Cuenta de prueba"}
