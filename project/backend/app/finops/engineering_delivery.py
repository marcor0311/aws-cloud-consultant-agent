"""Typed FinOps-to-Engineering handoff orchestrated by Codex."""

import hashlib
from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from app.finops.models import FinOpsModel


class EngineeringIssuePlan(FinOpsModel):
    contract_version: Literal["1.0"] = "1.0"
    case_id: str = Field(min_length=1, max_length=120)
    project_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,59}$")
    architecture_revision: int = Field(ge=1)
    architecture_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    repository_url: str = Field(pattern=r"^https://github\.com/[^/]+/[^/]+$")
    finops_issue_url: str = Field(
        pattern=r"^https://github\.com/[^/]+/[^/]+/issues/[0-9]+$"
    )
    finops_pull_request_url: str = Field(
        pattern=r"^https://github\.com/[^/]+/[^/]+/pull/[0-9]+$"
    )
    finops_merge_commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    engineer_github_username: str = Field(
        pattern=r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$"
    )
    title: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=20000)
    body_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    labels: list[str] = Field(min_length=1, max_length=20)
    assignees: list[str] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def body_and_assignment_match(self):
        if self.assignees != [self.engineer_github_username]:
            raise ValueError("El issue debe asignarse al ingeniero indicado.")
        if "engineering" not in self.labels:
            raise ValueError("El issue de Ingeniería requiere el label engineering.")
        if hashlib.sha256(self.body.encode()).hexdigest() != self.body_sha256:
            raise ValueError("El hash del issue de Ingeniería no coincide.")
        return self


class EngineeringIssueReceipt(FinOpsModel):
    contract_version: Literal["1.0"] = "1.0"
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    issue_url: str = Field(
        pattern=r"^https://github\.com/[^/]+/[^/]+/issues/[0-9]+$"
    )
    issue_number: int = Field(ge=1)
    body_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    assignees: list[str] = Field(min_length=1, max_length=20)
    state: Literal["open"] = "open"
    created_at: datetime

    @model_validator(mode="after")
    def created_at_is_aware(self):
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("created_at debe incluir zona horaria.")
        return self


class FinOpsEngineeringHandoff(FinOpsModel):
    contract_version: Literal["1.0"] = "1.0"
    handoff_status: Literal["ready"] = "ready"
    case_id: str = Field(min_length=1, max_length=120)
    project_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,59}$")
    architecture_revision: int = Field(ge=1)
    architecture_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    finops_issue_url: str = Field(
        pattern=r"^https://github\.com/[^/]+/[^/]+/issues/[0-9]+$"
    )
    engineering_issue_url: str = Field(
        pattern=r"^https://github\.com/[^/]+/[^/]+/issues/[0-9]+$"
    )
    finops_pull_request_url: str = Field(
        pattern=r"^https://github\.com/[^/]+/[^/]+/pull/[0-9]+$"
    )
    finops_merge_commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    estimate_urls: list[str] = Field(min_length=1, max_length=100)
    forecast_path: str = Field(
        pattern=r"^docs/04-finops/versions/v[0-9]{3}/forecast\.xlsx$"
    )
    forecast_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_path: str = Field(
        pattern=r"^docs/04-finops/versions/v[0-9]{3}/manifest\.json$"
    )
    budget_result: Literal["within_budget", "near_limit", "over_budget"]
    decision_id: str = Field(min_length=1, max_length=160)
    authorization_id: str = Field(min_length=1, max_length=160)
    created_at: datetime

    @model_validator(mode="after")
    def created_at_is_aware(self):
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("created_at debe incluir zona horaria.")
        return self


class EngineeringHandoffAcceptance(FinOpsModel):
    contract_version: Literal["1.0"] = "1.0"
    case_id: str = Field(min_length=1, max_length=120)
    architecture_revision: int = Field(ge=1)
    architecture_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    accepted_by: str = Field(min_length=1, max_length=160)
    accepted_at: datetime
    engineering_reference: str = Field(
        min_length=1, max_length=512, pattern=r"^(engineering|https)://"
    )
    status: Literal["accepted"] = "accepted"

    @model_validator(mode="after")
    def accepted_at_is_aware(self):
        if self.accepted_at.tzinfo is None or self.accepted_at.utcoffset() is None:
            raise ValueError("accepted_at debe incluir zona horaria.")
        return self
