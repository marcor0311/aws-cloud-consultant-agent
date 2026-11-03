"""Read-only adapter to the registry owned by the external business system."""

import os
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx


class WhitelistUnavailable(Exception):
    """An outage or invalid response must never be interpreted as non-registration."""


@dataclass(frozen=True)
class RegisteredContact:
    name: str
    enabled: bool


class HTTPWhitelist:
    def lookup(self, email: str) -> RegisteredContact | None:
        url = os.getenv("CALENDAR_WHITELIST_URL", "")
        key = os.getenv("CALENDAR_WHITELIST_API_KEY", "")
        parsed = urlsplit(url)
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
            or (parsed.scheme != "https" and not local_http)
        ):
            raise WhitelistUnavailable("Configura el endpoint interno de registro.")
        try:
            # POST avoids putting personal email addresses in URL/access logs.
            response = httpx.post(
                url,
                json={"email": email},
                headers={"Authorization": f"Bearer {key}"},
                timeout=5,
                follow_redirects=False,
            )
            response.raise_for_status()
            payload = response.json()
            if (
                not isinstance(payload, dict)
                or type(payload.get("registered")) is not bool
            ):
                raise ValueError("Respuesta de registro inválida.")
            if not payload["registered"]:
                return None
            if type(payload.get("enabled")) is not bool:
                raise ValueError("Falta el estado del registro.")
            name = payload.get("name")
            if not isinstance(name, str) or not name.strip() or len(name) > 120:
                raise ValueError("Falta el nombre registrado.")
            return RegisteredContact(name.strip(), payload["enabled"])
        except (httpx.HTTPError, ValueError, TypeError):
            raise WhitelistUnavailable("No se pudo consultar el registro.") from None
