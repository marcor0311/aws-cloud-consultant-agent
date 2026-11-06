"""Versioned demo contract. Simulated upstream data cannot claim real approvals."""

from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)


def nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("El valor no puede estar vacío")
    return value


Text = Annotated[str, Field(min_length=1, max_length=2000), AfterValidator(nonblank)]
Phase = Literal[
    "discovery", "prioritization", "architecture", "finops", "engineering", "report"
]
Provenance = Literal["real", "simulated"]
Money = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Activity(Contract):
    actor_id: Text
    actor_type: Literal["human", "agent"]
    kind: Literal["work", "wait", "rework"]
    started_at: AwareDatetime
    ended_at: AwareDatetime

    @model_validator(mode="after")
    def ordered(self):
        if self.ended_at < self.started_at:
            raise ValueError("La actividad termina antes de comenzar")
        return self


class PhaseTiming(Contract):
    phase: Phase
    provenance: Provenance
    accepted_at: AwareDatetime
    handed_off_at: AwareDatetime
    activities: list[Activity] = Field(max_length=100)

    @model_validator(mode="after")
    def bounded(self):
        if self.handed_off_at < self.accepted_at:
            raise ValueError("La entrega precede la aceptación")
        for activity in self.activities:
            if not (
                self.accepted_at
                <= activity.started_at
                <= activity.ended_at
                <= self.handed_off_at
            ):
                raise ValueError("Actividad fuera del intervalo de la fase")
        return self


class Source(Contract):
    provenance: Literal["simulated"] = "simulated"
    reference: Text
    revision: Text


class Baseline(Contract):
    module_id: Literal["s3"]
    repository: Literal[
        "https://github.com/marcor0311/aws-cloud-consultant-baseline-modules.git"
    ]
    commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    approval_status: Literal["pending"] = "pending"


class Architecture(Contract):
    source: Source
    approval_status: Literal["simulated_approved"] = "simulated_approved"
    region: str = Field(pattern=r"^[a-z]{2}(?:-[a-z]+)+-\d$")
    environment: Literal["dev", "test", "stage"]
    bucket_name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$")
    kms_key_arn: str = Field(
        pattern=r"^arn:aws:kms:[a-z0-9-]+:\d{12}:key/[a-zA-Z0-9-]+$"
    )
    baseline: Baseline


class FinOps(Contract):
    source: Source
    approval_status: Literal["simulated_approved"] = "simulated_approved"
    architecture_revision: Text
    budget_monthly: Money
    estimate_monthly: Money
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    period: Literal["month"] = "month"
    calculator_reference: Text
    spreadsheet_reference: Text
    assumptions: list[Text] = Field(min_length=1, max_length=20)


class DemoRequest(Contract):
    schema_version: Literal["1.0"] = "1.0"
    mode: Literal["demo"] = "demo"
    delivery_id: UUID
    project_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,59}$")
    project_name: str = Field(min_length=3, max_length=150)
    architecture: Architecture
    finops: FinOps
    upstream_timings: list[PhaseTiming] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def demo_timings(self):
        phases = [timing.phase for timing in self.upstream_timings]
        if len(phases) != len(set(phases)):
            raise ValueError("Una fase de entrada está repetida")
        for timing in self.upstream_timings:
            if timing.provenance != "simulated" or timing.phase in (
                "engineering",
                "report",
            ):
                raise ValueError(
                    "La entrada solo acepta tiempos simulados de fases anteriores"
                )
        return self


class ArtifactRef(Contract):
    artifact_id: UUID
    filename: str
    media_type: str
    sha256: str
    provenance: Literal["real"] = "real"


class Check(Contract):
    name: str
    status: Literal["passed", "failed", "not_run"]
    provenance: Provenance
    detail: str


class EngineeringHandoff(Contract):
    schema_version: Literal["1.0"] = "1.0"
    handoff_id: UUID
    delivery_id: UUID
    project_id: str
    created_at: AwareDatetime
    status: Literal["ready_for_draft"] = "ready_for_draft"
    implementation_status: Literal["prepared"] = "prepared"
    review_status: Literal["pending"] = "pending"
    integration_status: Literal["no_pr"] = "no_pr"
    summary: str
    inputs: dict
    costs: FinOps
    checks: list[Check]
    artifacts: list[ArtifactRef]
    timings: list[PhaseTiming]
    pending_items: list[str]


class ReportDraft(Contract):
    schema_version: Literal["1.0"] = "1.0"
    report_id: UUID
    handoff_id: UUID
    version: Literal[1] = 1
    status: Literal["draft"] = "draft"
    artifact: ArtifactRef
    metrics: dict
    pending_items: list[str]
