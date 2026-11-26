"""Read-only authorization probes: no application calls, email, inference or writes."""

import json
import os
import time
from functools import lru_cache, partial

from google.auth.exceptions import GoogleAuthError, RefreshError, TransportError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from app.core.config import private_path
from app.notifications.gmail import GMAIL_SEND_SCOPE


def failure(code, message):
    return {"status": "error", "code": code, "message": message}


@lru_cache(maxsize=16)
def _probe_token(path, modified, size, interval):
    # File metadata and the time bucket invalidate cached results. Refresh only
    # in memory, including when the access token has not expired yet: that token
    # alone cannot tell us whether Google revoked the renewal authorization.
    try:
        info = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(info, dict):
            raise ValueError
        if info.get("token_uri") != "https://oauth2.googleapis.com/token":
            return failure(
                "invalid_token_endpoint", "El endpoint OAuth no es de Google."
            )
        credentials = Credentials.from_authorized_user_info(info)
        credentials.refresh(partial(Request(), timeout=5))
        scopes = info.get("scopes", [])
        if not isinstance(scopes, list) or not all(isinstance(s, str) for s in scopes):
            raise ValueError
        return {"status": "ok", "scopes": scopes}
    except RefreshError as error:
        payload = next((arg for arg in error.args if isinstance(arg, dict)), {})
        code = payload.get("error")
        messages = {
            "invalid_grant": "Google rechazó renovar la autorización: pudo vencer, "
            "ser revocada o requerir nuevo consentimiento.",
            "invalid_client": "Google rechazó las credenciales del cliente OAuth.",
            "unauthorized_client": "El cliente OAuth no está autorizado para renovar el acceso.",
            "invalid_scope": "Google rechazó los permisos solicitados.",
            "invalid_request": "Google rechazó la solicitud de renovación OAuth.",
            "temporarily_unavailable": "El servicio OAuth de Google no está disponible temporalmente.",
            "server_error": "El servidor OAuth de Google falló.",
        }
        if payload.get("error_subtype") == "invalid_rapt":
            return failure(
                "invalid_rapt",
                "La política de sesión de Google exige autenticarse otra vez.",
            )
        if isinstance(code, str) and code in messages:
            return failure(code, messages[code])
        return failure(
            "oauth_refresh_failed",
            "Google no pudo renovar el acceso; causa no reconocida.",
        )
    except TransportError:
        return failure(
            "oauth_transport_error",
            "No se pudo contactar Google; revisá conexión, DNS o proxy.",
        )
    except (OSError, ValueError, TypeError, GoogleAuthError):
        return failure(
            "invalid_credentials",
            "No se pudo leer o validar el archivo de autorización.",
        )


def _google_check(variable, command, required_scopes=()):
    try:
        path = private_path(os.environ[variable]).resolve()
        info = path.stat()
        result = _probe_token(
            path, info.st_mtime_ns, info.st_size, int(time.monotonic() // 30)
        )
    except (KeyError, OSError, ValueError):
        result = failure(
            "token_unavailable",
            f"Falta el archivo de autorización de {variable} o no se puede leer.",
        )
    result = dict(result)
    scopes = result.pop("scopes", [])
    if result["status"] == "ok" and not set(required_scopes).issubset(scopes):
        result = failure(
            "missing_scopes", "El token no declara todos los permisos necesarios."
        )
    if result["status"] == "ok":
        result["message"] = "Google aceptó renovar la autorización."
    elif result["code"] in {
        "oauth_transport_error",
        "temporarily_unavailable",
        "server_error",
    }:
        result["action"] = "Revisá la conexión o volvé a consultar health más tarde."
    else:
        result["action"] = f"Ejecutá {command} y completá el consentimiento de Google."
    return result


def check_health():
    checks = {}
    service_key = os.getenv("CALENDAR_ACCESS_SERVICE_KEY", "")
    code_secret = os.getenv("CALENDAR_ACCESS_CODE_SECRET", "")
    checks["verification"] = (
        {"status": "ok"}
        if len(service_key) >= 32
        and len(code_secret) >= 32
        and service_key != code_secret
        else failure(
            "verification_configuration",
            "Configurá CALENDAR_ACCESS_SERVICE_KEY y "
            "CALENDAR_ACCESS_CODE_SECRET independientes, de al menos 32 caracteres.",
        )
    )
    if os.getenv("CALENDAR_ASSISTANT_MODE") == "mock":
        checks["calendar"] = {
            "status": "skipped",
            "message": "Agente de calendario en modo mock.",
        }
    else:
        checks["calendar"] = _google_check(
            "GOOGLE_OAUTH_TOKEN_FILE", "make calendar-auth"
        )
    provider = os.getenv("CALENDAR_MAIL_PROVIDER", "smtp").strip().lower()
    if provider == "gmail":
        checks["gmail"] = _google_check(
            "CALENDAR_GMAIL_TOKEN_FILE", "make gmail-auth", (GMAIL_SEND_SCOPE,)
        )
    else:
        checks["gmail"] = {
            "status": "skipped",
            "message": "Gmail no es el proveedor de correo seleccionado.",
        }
    if (
        os.getenv("WORKFLOW_ENABLED") == "1"
        and os.getenv("WORKFLOW_MODE", "mock") == "live"
    ):
        # Sharing the Calendar file reuses the cached probe, without renewing twice.
        workflow_path = private_path(os.getenv("WORKFLOW_GOOGLE_TOKEN_FILE", ""))
        calendar_path = private_path(os.getenv("GOOGLE_OAUTH_TOKEN_FILE", ""))
        command = (
            "make calendar-auth"
            if workflow_path.resolve() == calendar_path.resolve()
            else "make workflow-auth (conservar primero el token anterior como respaldo privado)"
        )
        checks["workflow_google"] = _google_check("WORKFLOW_GOOGLE_TOKEN_FILE", command)
    else:
        checks["workflow_google"] = {
            "status": "skipped",
            "message": "Workflow real desactivado.",
        }
    return {
        "status": "degraded"
        if any(c["status"] == "error" for c in checks.values())
        else "ok",
        "checks": checks,
        "scope": "verification_configuration_and_google_oauth",
        "cache_seconds": 30,
    }
