"""Structured correction requests sent by FinOps to Architecture."""

from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class CorrectionContract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AffectedDimension(CorrectionContract):
    resource_id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,62}$")
    dimension_id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,62}$")


class FinOpsCorrectionRequest(CorrectionContract):
    contract_version: Literal["1.0"] = "1.0"
    request_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
    architecture_id: str = Field(min_length=1, max_length=120)
    project_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,59}$")
    source_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=2000)
    affected_resources: list[str] = Field(default_factory=list, max_length=100)
    affected_dimensions: list[AffectedDimension] = Field(
        default_factory=list, max_length=200
    )
    requested_changes: list[str] = Field(min_length=1, max_length=100)
    new_constraints: list[str] = Field(default_factory=list, max_length=100)
    finops_evaluation_reference: str = Field(
        min_length=1,
        max_length=500,
        pattern=r"^(?:finops|artifact|https)://[^\s]+$",
    )
    requested_at: AwareDatetime
    requested_by: Literal["finops-agent"]
    origin: Literal["finops"] = "finops"

    @model_validator(mode="after")
    def affected_scope_is_coherent(self):
        if not self.affected_resources and not self.affected_dimensions:
            raise ValueError("La corrección debe identificar recursos o dimensiones.")
        resources = self.affected_resources
        if len(resources) != len(set(resources)):
            raise ValueError("Los recursos afectados no pueden repetirse.")
        dimensions = [
            (item.resource_id, item.dimension_id)
            for item in self.affected_dimensions
        ]
        if len(dimensions) != len(set(dimensions)):
            raise ValueError("Las dimensiones afectadas no pueden repetirse.")
        return self

    @property
    def requested_at_utc(self) -> datetime:
        return self.requested_at

