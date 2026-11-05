"""Per-process call identity for the local stdio MCP server (one server per call)."""

import json
import os
import re
import threading
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class AccessClient:
    def __init__(self):
        # Never exposed as model arguments. A new MCP subprocess means a new call.
        self.session_id = uuid.uuid4().hex
        self.origin_id = os.getenv("CALENDAR_ACCESS_ORIGIN_ID", "calendar-assistant")
        self.email = ""
        self.challenge_id = ""
        self._lock = threading.RLock()

    def _request(self, endpoint: str, **payload) -> dict:
        base = os.getenv("CALENDAR_ACCESS_URL", "").rstrip("/")
        key = os.getenv("CALENDAR_ACCESS_SERVICE_KEY", "")
        parsed = urlsplit(base)
        local_http = parsed.scheme == "http" and parsed.hostname in {
            "localhost",
            "127.0.0.1",
            "::1",
        }
        if (
            not key
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.fragment
            or parsed.query
            or (parsed.scheme != "https" and not local_http)
        ):
            return {"status": "unavailable"}
        request = Request(
            f"{base}/{endpoint}",
            data=json.dumps({"session_id": self.session_id, **payload}).encode(),
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with build_opener(NoRedirects()).open(request, timeout=25) as response:
                result = json.load(response)
            if not isinstance(result, dict) or not isinstance(
                result.get("status"), str
            ):
                return {"status": "unavailable"}
            return result
        except (HTTPError, URLError, TimeoutError, OSError, ValueError):
            return {"status": "unavailable"}

    @staticmethod
    def _public(result: dict) -> dict:
        # Session IDs, challenge IDs and credentials stay outside the LLM context.
        response = {"estado": result.get("status", "unavailable")}
        for field in (
            "attempts_remaining",
            "retry_after_seconds",
            "expires_in_seconds",
        ):
            if type(result.get(field)) is int:
                response[field] = result[field]
        if response["estado"] in {"not_registered", "not_enabled"}:
            response["mensaje"] = (
                "Debe hablar con un asesor de negocio para completar su registro."
            )
        return response

    def start(self, email: str) -> dict:
        with self._lock:
            if self.email != email:
                self.challenge_id = ""
            self.email = email
            result = self._request("start", email=email, origin_id=self.origin_id)
            if result.get("status") == "code_sent":
                challenge = result.get("challenge_id", "")
                if not isinstance(challenge, str) or len(challenge) < 20:
                    self.challenge_id = ""
                    return {"estado": "unavailable"}
                self.challenge_id = challenge
            elif result.get("status") != "rate_limited":
                self.challenge_id = ""
            return self._public(result)

    def verify(self, code: str) -> dict:
        with self._lock:
            if not self.challenge_id:
                return {"estado": "verification_required"}
            # Preserve zeros; only remove separators in already transcribed digits.
            code = re.sub(r"[\s,-]", "", code)
            if not re.fullmatch(r"[0-9]{6}", code):
                return {"estado": "invalid_format"}
            result = self._request("verify", challenge_id=self.challenge_id, code=code)
            if result.get("status") == "verified" and result.get("email") != self.email:
                return {"estado": "unavailable"}
            return self._public(result)

    def resend(self) -> dict:
        with self._lock:
            if not self.challenge_id:
                return {"estado": "verification_required"}
            result = self._request("resend", challenge_id=self.challenge_id)
            if result.get("status") == "code_sent":
                challenge = result.get("challenge_id", "")
                if not isinstance(challenge, str) or len(challenge) < 20:
                    return {"estado": "unavailable"}
                self.challenge_id = challenge
            return self._public(result)

    def require(self, operation: str, email: str = "") -> None:
        with self._lock:
            target = email.strip().lower() if email else self.email
            if not target or not self.email or target != self.email:
                raise ValueError(
                    "Primero verifica el correo de esta llamada con el código enviado."
                )
            result = self._request("authorize", email=target, operation=operation)
            if result.get("status") == "unavailable":
                raise RuntimeError(
                    "No pude comprobar la autorización. Intente de nuevo más tarde."
                )
            if result.get("status") != "authorized" or result.get("email") != target:
                raise ValueError(
                    "Necesita verificar su correo registrado con un código antes de continuar."
                )

    def close(self):
        with self._lock:
            if self.email:
                self._request("close")
            self.email = ""
            self.challenge_id = ""
