"""Read-only whitelist contract and replaceable storage adapters."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

import httpx

from app.config import project_path
from app.models.calendar_access import normalize_email


class WhitelistUnavailable(Exception):
    """An outage or invalid response must never be interpreted as non-registration."""


@dataclass(frozen=True)
class RegisteredContact:
    name: str
    enabled: bool


class Whitelist(Protocol):
    """A database adapter can implement this contract without changing verification."""

    def lookup(self, email: str) -> RegisteredContact | None: ...


@dataclass(frozen=True)
class MarkdownWhitelist:
    path: Path

    def lookup(self, email: str) -> RegisteredContact | None:
        try:
            # Read for every lookup so edits and revocations apply immediately.
            lines = self.path.read_text(encoding="utf-8").splitlines()
            rows = [line.strip() for line in lines if line.strip().startswith("|")]
            if len(rows) < 2 or rows[0] != "| email | name | enabled |":
                raise ValueError("Falta la cabecera de la whitelist.")
            if rows[1] != "| --- | --- | --- |":
                raise ValueError("Separador de tabla inválido.")
            contacts = {}
            for row in rows[2:]:
                if not row.endswith("|"):
                    raise ValueError("Fila incompleta.")
                cells = [cell.strip() for cell in row[1:-1].split("|")]
                if len(cells) != 3:
                    raise ValueError("Registro inválido.")
                address, name, enabled = cells
                address = normalize_email(address)
                if (
                    address in contacts
                    or not name
                    or len(name) > 120
                    or enabled not in {"true", "false"}
                ):
                    raise ValueError("Registro inválido o duplicado.")
                contacts[address] = RegisteredContact(name, enabled == "true")
            return contacts.get(normalize_email(email))
        except (OSError, UnicodeError, ValueError):
            raise WhitelistUnavailable(
                "No se pudo leer la whitelist privada."
            ) from None


def configured_whitelist() -> Whitelist:
    provider = os.getenv("CALENDAR_WHITELIST_PROVIDER", "file").strip().lower()
    if provider == "file":
        return MarkdownWhitelist(
            project_path(os.getenv("CALENDAR_WHITELIST_FILE", "whitelist.md"))
        )
    if provider == "http":
        return HTTPWhitelist()
    raise ValueError("El proveedor de whitelist no es válido.")


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
