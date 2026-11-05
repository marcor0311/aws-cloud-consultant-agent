"""Validated payloads for the internal calendar access API."""

import re
from typing import Literal

from pydantic import BaseModel, Field, SecretStr, field_validator


def normalize_email(value: str) -> str:
    email = value.strip().lower()
    if len(email) > 254 or not re.fullmatch(
        r"[a-z0-9._%+-]+@[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,}", email
    ):
        raise ValueError("El correo no tiene un formato válido.")
    local, domain = email.rsplit("@", 1)
    if (
        len(local) > 64
        or local.startswith(".")
        or local.endswith(".")
        or ".." in email
        or any(part.startswith("-") or part.endswith("-") for part in domain.split("."))
    ):
        raise ValueError("El correo no tiene un formato válido.")
    return email


class Payload(BaseModel):
    model_config = {"extra": "forbid", "str_strip_whitespace": True}


class EmailPayload(Payload):
    email: str = Field(max_length=254)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        return normalize_email(value)


class SessionPayload(Payload):
    session_id: str = Field(min_length=16, max_length=128, pattern=r"^[a-zA-Z0-9_:-]+$")


class StartVerification(SessionPayload, EmailPayload):
    # Supplied by the trusted calling service, never by the conversational model.
    origin_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_:-]+$")


class ChallengePayload(SessionPayload):
    challenge_id: str = Field(min_length=20, max_length=128)


class VerifyCode(ChallengePayload):
    code: SecretStr

    @field_validator("code")
    @classmethod
    def valid_code(cls, value: SecretStr) -> SecretStr:
        if not re.fullmatch(r"[0-9]{6}", value.get_secret_value()):
            raise ValueError("El código debe contener seis dígitos.")
        return value


class AuthorizeOperation(SessionPayload, EmailPayload):
    operation: Literal["availability", "search", "book", "reschedule", "cancel"]
