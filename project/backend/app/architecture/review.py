"""Typed human decision recorded by Codex for an exact architecture revision."""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class ArchitectureReviewDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    contract_version: Literal["1.0"] = "1.0"
    case_id: str = Field(min_length=1, max_length=120)
    revision: int = Field(ge=1)
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: Literal["approve", "revise"]
    feedback: str = Field(default="", max_length=12000)
    architect: str = Field(min_length=1, max_length=200)
    decided_at: AwareDatetime
    confirmation_source: Literal["codex_conversation"]
    confirmation_reference: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def revision_requires_feedback(self):
        if self.decision == "revise" and not self.feedback:
            raise ValueError("Indicar los ajustes solicitados.")
        return self
