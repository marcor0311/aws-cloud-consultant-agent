"""Client identity, code generation and registry contract."""

import re
import secrets
import string
from dataclasses import dataclass
from typing import Protocol


class RegistryUnavailable(Exception):
    """Storage failure, distinct from an unknown client."""


def normalize_client_code(value: str) -> str:
    code = value.strip().upper()
    if not re.fullmatch(r"[A-Z]{4}-[0-9]{4}", code, flags=re.ASCII):
        raise ValueError("El código de cliente debe tener el formato XXXX-0000.")
    return code


def generate_client_code() -> str:
    letters = "".join(secrets.choice(string.ascii_uppercase) for _ in range(4))
    return f"{letters}-{secrets.randbelow(10_000):04d}"


@dataclass(frozen=True)
class Client:
    client_id: int
    client_code: str
    company_name: str
    company_email: str
    enabled: bool


class ClientRegistry(Protocol):
    def lookup_code(self, client_code: str) -> Client | None: ...
