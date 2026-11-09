"""Validated payloads for the internal calendar access API."""

import re
from typing import Literal

from pydantic import BaseModel, Field, SecretStr, field_validator

from app.core.validation import normalize_email


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


class StartVerification(SessionPayload):
    client_code: str = Field(
        min_length=9, max_length=9, pattern=r"^[A-Za-z]{4}-[0-9]{4}$"
    )

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
