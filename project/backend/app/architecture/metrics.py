"""Typed persistence boundary for Architecture timing and FinOps acceptance."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FinOpsHandoffAcceptance(BaseModel):
    """Receipt returned by FinOps after consuming one exact Architecture handoff."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    contract_version: Literal["1.0"] = "1.0"
    case_id: str = Field(min_length=1, max_length=120)
    revision: int = Field(ge=1)
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    accepted_by: str = Field(min_length=1, max_length=160)
    accepted_at: datetime
    status: Literal["accepted"] = "accepted"
    finops_reference: str = Field(
        min_length=1,
        max_length=512,
        pattern=r"^(finops|https)://",
    )

    @field_validator("accepted_at")
    @classmethod
    def timestamp_must_have_timezone(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("accepted_at debe incluir zona horaria.")
        return value
