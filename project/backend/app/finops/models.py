"""FinOps-owned contracts; shared Architecture contracts are imported, not copied."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.architecture.metrics import FinOpsHandoffAcceptance
from app.architecture.models import ArchitectureFinOpsHandoff


class FinOpsModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class FinOpsIntake(FinOpsModel):
    """Immutable record that FinOps consumed one exact Architecture revision."""

    contract_version: Literal["1.0"] = "1.0"
    case_id: str = Field(min_length=1, max_length=120)
    project_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,59}$")
    operational_status: Literal["received"] = "received"
    handoff: ArchitectureFinOpsHandoff
    acceptance: FinOpsHandoffAcceptance

    @model_validator(mode="after")
    def references_exact_handoff(self):
        if self.project_id != self.handoff.architecture.project_id:
            raise ValueError("El expediente FinOps corresponde a otro proyecto.")
        if self.case_id != self.acceptance.case_id:
            raise ValueError("El recibo corresponde a otro expediente.")
        if self.handoff.revision != self.acceptance.revision:
            raise ValueError("El recibo corresponde a otra revisión.")
        if self.handoff.artifact_sha256 != self.acceptance.artifact_sha256:
            raise ValueError("El recibo corresponde a otro artefacto.")
        return self


class FinOpsEvaluationDecision(FinOpsModel):
    """Authorized outcome of an evaluation, independent from handoff receipt."""

    contract_version: Literal["1.0"] = "1.0"
    decision_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,159}$")
    case_id: str = Field(min_length=1, max_length=120)
    project_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,59}$")
    architecture_revision: int = Field(ge=1)
    architecture_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluation_reference: str = Field(
        min_length=1, max_length=512, pattern=r"^(finops|https)://"
    )
    budget_result: Literal[
        "within_budget", "near_limit", "over_budget", "not_evaluable"
    ]
    decision: Literal[
        "approved",
        "information_required",
        "architecture_correction_required",
        "unverifiable",
    ]
    rationale: str = Field(min_length=1, max_length=2000)
    decided_by: str = Field(min_length=1, max_length=160)
    decided_at: datetime
    authorization_reference: str | None = Field(
        default=None, min_length=1, max_length=512
    )

    @model_validator(mode="after")
    def approval_requires_explicit_authorization(self):
        if self.decided_at.tzinfo is None or self.decided_at.utcoffset() is None:
            raise ValueError("decided_at debe incluir zona horaria.")
        if self.decision == "approved" and not self.authorization_reference:
            raise ValueError("La aprobación requiere autorización trazable.")
        if self.decision != "approved" and self.authorization_reference:
            raise ValueError("Solo una aprobación puede declarar autorización.")
        return self
