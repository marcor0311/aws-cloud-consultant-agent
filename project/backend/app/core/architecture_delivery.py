"""Versioned transport from Project Opening (Agent 2) to Architecture (Agent 3)."""

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DeliveryContract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DeliveryFile(DeliveryContract):
    path: str = Field(pattern=r"^docs/(01-discovery|02-board)/[^/]+$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    media_type: Literal[
        "text/markdown", "text/html", "application/json", "application/pdf"
    ]


class DeliveryManifest(DeliveryContract):
    revision: int = Field(ge=1)
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    files_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    path: Literal["docs/01-discovery/manifest.json"] | None = None
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def path_and_hash_are_atomic(self):
        if bool(self.path) != bool(self.sha256):
            raise ValueError("La ruta y el hash del manifiesto deben declararse juntos.")
        return self


class DeliveryBudgetLine(DeliveryContract):
    name: str = Field(min_length=1, max_length=100)
    amount: Decimal = Field(ge=0, max_digits=14, decimal_places=2)


class DeliveryBudget(DeliveryContract):
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    total: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    accepted: Literal[True]
    lines: list[DeliveryBudgetLine] = Field(min_length=1)
    conditions: str = Field(min_length=1, max_length=12000)

    @model_validator(mode="after")
    def lines_match_total(self):
        if sum((line.amount for line in self.lines), Decimal("0")) != self.total:
            raise ValueError("Las partidas no suman el presupuesto aprobado.")
        return self


class ArchitectureWork(DeliveryContract):
    context: str = Field(min_length=1, max_length=12000)
    scope: str = Field(min_length=1, max_length=12000)
    restrictions: str = Field(min_length=1, max_length=12000)
    deliverables: str = Field(min_length=1, max_length=12000)
    acceptance: str = Field(min_length=1, max_length=12000)


class DirectionDecision(DeliveryContract):
    kind: Literal["direction_decision"]
    id: str = Field(min_length=1, max_length=120)
    actor: str = Field(min_length=1, max_length=160)
    reference: str = Field(min_length=1, max_length=1000)
    approved_at: float = Field(ge=0)
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    simulated: Literal[False] = False


class BoardDecision(DeliveryContract):
    kind: Literal["board_record"]
    id: str = Field(min_length=1, max_length=200)
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["approved"]
    closed_at: str = Field(min_length=1, max_length=100)
    review_url: str = Field(min_length=1, max_length=1000)
    simulated: bool
    document_path: str = Field(pattern=r"^docs/02-board/[^/]+\.json$")
    document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    signature_verification: Literal["declared_by_source"] = "declared_by_source"


OpeningDecision = Annotated[
    DirectionDecision | BoardDecision, Field(discriminator="kind")
]


class RepositoryReceipt(DeliveryContract):
    url: str = Field(pattern=r"^https://github\.com/[^/]+/[^/]+$")
    full_name: str = Field(pattern=r"^[^/]+/[^/]+$")
    default_branch: str = Field(min_length=1, max_length=255)
    id: int = Field(ge=1)


class CommitReceipt(DeliveryContract):
    sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    url: str


class PullRequestReceipt(DeliveryContract):
    number: int = Field(ge=1)
    url: str
    merged: Literal[True]
    merge_sha: str = Field(pattern=r"^[0-9a-f]{40}$")


class ArchitectureIssueReceipt(DeliveryContract):
    number: int = Field(ge=1)
    url: str = Field(pattern=r"^https://github\.com/[^/]+/[^/]+/issues/[0-9]+$")
    title: str = Field(min_length=1, max_length=500)
    assignee: str = Field(min_length=1, max_length=39)
    assignment_pending: Literal[False]
    template_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    body_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class WorkflowHandoffReceipt(DeliveryContract):
    id: str = Field(min_length=1, max_length=256)
    from_actor: Literal["meeting-assistant"]
    to_actor: str = Field(min_length=1, max_length=160)
    from_phase: Literal["project-opening"]
    to_phase: Literal["architecture"]
    revision: int = Field(ge=1)
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: float = Field(ge=0)
    accepted_at: float | None = Field(default=None, ge=0)
    accepted_by: str | None = None


class ArchitectureProjectDelivery(DeliveryContract):
    """Agent 2 output. A local checkout path is deliberately not transport data."""

    contract_version: Literal["1.3"] = "1.3"
    source_stage: Literal[2] = 2
    case_id: str = Field(min_length=1, max_length=120)
    project_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,99}$")
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    architect: str = Field(min_length=1, max_length=39)
    repository: RepositoryReceipt
    published_commit: CommitReceipt
    initial_pull_request: PullRequestReceipt
    architecture_issue: ArchitectureIssueReceipt
    approved_package: DeliveryManifest
    inputs: list[DeliveryFile] = Field(min_length=1, max_length=100)
    budget: DeliveryBudget
    work: ArchitectureWork
    approval: OpeningDecision
    handoff: WorkflowHandoffReceipt
    is_fictitious: bool

    @model_validator(mode="after")
    def traceability_is_consistent(self):
        if self.repository.full_name.casefold() not in self.repository.url.casefold():
            raise ValueError("El repositorio no coincide con su recibo.")
        base = self.repository.url
        if not self.architecture_issue.url.startswith(base + "/issues/"):
            raise ValueError("El issue pertenece a otro repositorio.")
        if self.architecture_issue.assignee.casefold() != self.architect.casefold():
            raise ValueError("El issue no está asignado al arquitecto esperado.")
        if self.approval.request_sha256 != self.request_sha256:
            raise ValueError("La decisión corresponde a otra solicitud.")
        if self.handoff.to_actor.casefold() != self.architect.casefold():
            raise ValueError("El handoff no está dirigido al arquitecto esperado.")
        if self.handoff.artifact_sha256 != self.approval.digest:
            raise ValueError("El handoff no corresponde a la decisión aprobada.")
        paths = [item.path for item in self.inputs]
        if len(paths) != len(set(paths)):
            raise ValueError("Las evidencias no pueden repetirse.")
        return self
