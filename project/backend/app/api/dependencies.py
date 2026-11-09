"""FastAPI authentication and lifecycle, using the shared application composition."""

import hmac
import os
import sqlite3
import threading
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.bootstrap import create_access_service, create_opening_runtime, create_runtime
from app.core.config import PROJECT_DIR
from app.workflow.settings import WorkflowSettings

bearer = HTTPBearer(auto_error=False)
runtime_lock = threading.Lock()
_runtime = None
_opening_runtime = None


def get_call_receipt_key():
    return os.getenv("CALENDAR_ACCESS_SERVICE_KEY", "")


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


def require_manager(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
):
    token = WorkflowSettings.from_environment().manager_token
    if len(token) < 32:
        raise HTTPException(503, "Configurar la credencial del Engagement Manager.")
    if not credentials or not hmac.compare_digest(
        credentials.credentials.encode(), token.encode()
    ):
        raise HTTPException(
            401, "Credencial inválida.", headers={"WWW-Authenticate": "Bearer"}
        )


def require_transcript_capture(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
):
    token = WorkflowSettings.from_environment().transcript_token
    if len(token) < 32:
        raise HTTPException(503, "La recepción de transcripts no está configurada.")
    if not credentials or not hmac.compare_digest(
        credentials.credentials.encode(), token.encode()
    ):
        raise HTTPException(401, "Credencial de captura inválida.")


@lru_cache(maxsize=1)
def get_access_service():
    try:
        return create_access_service()
    except (ValueError, OSError, sqlite3.Error) as error:
        message = (
            "Configura claves independientes para el acceso."
            if str(error) == "independent_access_keys_required"
            else "El acceso al calendario no está disponible."
        )
        raise HTTPException(503, message) from None


def get_runtime():
    global _runtime
    settings = WorkflowSettings.from_environment()
    if not settings.enabled:
        raise HTTPException(503, "El flujo de reuniones está deshabilitado.")
    with runtime_lock:
        if _runtime is None:
            _runtime = create_runtime(
                settings, client_lookup=get_access_service().clients.lookup_code
            )
        return _runtime


def clear_runtime():
    global _runtime, _opening_runtime
    with runtime_lock:
        if _runtime is not None:
            _runtime.close()
            _runtime = None
        if _opening_runtime is not None:
            _opening_runtime.close()
            _opening_runtime = None


def get_opening_runtime():
    global _opening_runtime
    with runtime_lock:
        if _opening_runtime is None:
            try:
                _opening_runtime = create_opening_runtime(
                    os.getenv("WORKFLOW_DATABASE_URL", ""),
                    PROJECT_DIR.parent / "insumos temporales de agente 1",
                    PROJECT_DIR
                    / "agents/2. meeting assistant/templates/architecture.md",
                )
            except ValueError:
                raise HTTPException(
                    503, "Configurar PostgreSQL para la junta directiva."
                ) from None
        return _opening_runtime
