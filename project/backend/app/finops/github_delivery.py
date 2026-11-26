"""Typed GitHub plans and receipts for FinOps, executed externally by Codex."""

import base64
import hashlib
from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from app.finops.models import FinOpsModel


class FinOpsGitHubFile(FinOpsModel):
    model_config = {"extra": "forbid", "str_strip_whitespace": False}

    path: str = Field(min_length=1, max_length=500)
    encoding: Literal["utf-8", "base64"]
    content: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def path_and_hash_match(self):
        if not self.path.startswith("docs/04-finops/versions/v") or ".." in self.path:
            raise ValueError("Los archivos deben pertenecer a la revisión FinOps.")
        try:
            raw = (
                self.content.encode()
                if self.encoding == "utf-8"
                else base64.b64decode(self.content, validate=True)
            )
        except ValueError as error:
            raise ValueError("El contenido base64 no es válido.") from error
        if hashlib.sha256(raw).hexdigest() != self.sha256:
            raise ValueError("El SHA-256 del archivo FinOps no coincide.")
        return self


class FinOpsCorrectionGitHubPlan(FinOpsModel):
    contract_version: Literal["1.0"] = "1.0"
    case_id: str = Field(min_length=1, max_length=120)
    project_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,59}$")
    architecture_revision: int = Field(ge=1)
    architecture_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    correction_request_id: str = Field(min_length=1, max_length=160)
    repository_url: str = Field(pattern=r"^https://github\.com/[^/]+/[^/]+$")
    finops_issue_url: str = Field(
        pattern=r"^https://github\.com/[^/]+/[^/]+/issues/[0-9]+$"
    )
    close_with_label: Literal["requiere-ajustes"] = "requiere-ajustes"
    closing_comment: str = Field(min_length=1, max_length=10000)
    closing_comment_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    architect_github_username: str = Field(
        pattern=r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$"
    )
    correction_issue_title: str = Field(min_length=1, max_length=300)
    correction_issue_body: str = Field(min_length=1, max_length=20000)
    correction_issue_labels: list[str] = Field(min_length=1, max_length=20)
    correction_issue_assignees: list[str] = Field(min_length=1, max_length=20)
    correction_issue_body_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def issue_is_assigned_and_hashed(self):
        if self.correction_issue_assignees != [self.architect_github_username]:
            raise ValueError("El issue de corrección debe asignarse al arquitecto.")
        if "architecture-correction" not in self.correction_issue_labels:
            raise ValueError("El issue requiere el label architecture-correction.")
        digest = hashlib.sha256(self.correction_issue_body.encode()).hexdigest()
        if digest != self.correction_issue_body_sha256:
            raise ValueError("El hash del issue de corrección no coincide.")
        if hashlib.sha256(self.closing_comment.encode()).hexdigest() != (
            self.closing_comment_sha256
        ):
            raise ValueError("El hash del comentario de cierre no coincide.")
        return self


class FinOpsCorrectionGitHubReceipt(FinOpsModel):
    contract_version: Literal["1.0"] = "1.0"
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    finops_issue_url: str = Field(
        pattern=r"^https://github\.com/[^/]+/[^/]+/issues/[0-9]+$"
    )
    finops_issue_state: Literal["closed"]
    finops_issue_labels: list[str] = Field(min_length=1, max_length=30)
    finops_closing_comment_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    correction_issue_url: str = Field(
        pattern=r"^https://github\.com/[^/]+/[^/]+/issues/[0-9]+$"
    )
    correction_issue_number: int = Field(ge=1)
    correction_issue_body_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    correction_issue_assignees: list[str] = Field(min_length=1, max_length=20)
    executed_at: AwareDatetime


class FinOpsGitHubPublicationPlan(FinOpsModel):
    contract_version: Literal["1.0"] = "1.0"
    case_id: str = Field(min_length=1, max_length=120)
    project_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,59}$")
    architecture_revision: int = Field(ge=1)
    architecture_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision_id: str = Field(min_length=1, max_length=160)
    authorization_id: str = Field(min_length=1, max_length=160)
    repository_url: str = Field(pattern=r"^https://github\.com/[^/]+/[^/]+$")
    source_issue_url: str = Field(
        pattern=r"^https://github\.com/[^/]+/[^/]+/issues/[0-9]+$"
    )
    base_branch: Literal["main"] = "main"
    base_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    branch: str = Field(pattern=r"^agent4/[a-z0-9][a-z0-9-]*/finops-v[0-9]{3}$")
    commit_message: str = Field(min_length=1, max_length=200)
    pull_request_title: str = Field(min_length=1, max_length=300)
    pull_request_body: str = Field(min_length=1, max_length=20000)
    files: list[FinOpsGitHubFile] = Field(min_length=1, max_length=200)
    requires_architect_review: Literal[False] = False
    merge_requires_successful_checks: Literal[True] = True


class FinOpsGitHubPullRequestReceipt(FinOpsModel):
    contract_version: Literal["1.0"] = "1.0"
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    repository_url: str = Field(pattern=r"^https://github\.com/[^/]+/[^/]+$")
    branch: str = Field(min_length=1, max_length=300)
    base_branch: Literal["main"]
    base_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    files: list[dict[str, str]] = Field(min_length=1, max_length=200)
    pull_request_number: int = Field(ge=1)
    pull_request_url: str = Field(
        pattern=r"^https://github\.com/[^/]+/[^/]+/pull/[0-9]+$"
    )
    state: Literal["open"]
    created_at: AwareDatetime


class FinOpsGitHubCheckReceipt(FinOpsModel):
    name: str = Field(min_length=1, max_length=200)
    status: Literal["completed"]
    conclusion: Literal["success"]
    details_url: str = Field(min_length=1, max_length=1000)


class FinOpsGitHubMergeReceipt(FinOpsModel):
    contract_version: Literal["1.0"] = "1.0"
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    authorization_id: str = Field(min_length=1, max_length=160)
    repository_url: str = Field(pattern=r"^https://github\.com/[^/]+/[^/]+$")
    pull_request_number: int = Field(ge=1)
    pull_request_url: str = Field(
        pattern=r"^https://github\.com/[^/]+/[^/]+/pull/[0-9]+$"
    )
    head_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    checks: list[FinOpsGitHubCheckReceipt] = Field(min_length=1, max_length=100)
    github_self_approval: Literal[False] = False
    pull_request_state: Literal["closed"]
    merged: Literal[True]
    merged_at: AwareDatetime
    merge_commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    source_issue_url: str = Field(
        pattern=r"^https://github\.com/[^/]+/[^/]+/issues/[0-9]+$"
    )
    source_issue_state: Literal["closed"]
    source_issue_closed_at: AwareDatetime
    observed_at: AwareDatetime

    @model_validator(mode="after")
    def times_are_coherent(self):
        if not (
            self.merged_at <= self.observed_at
            and self.source_issue_closed_at <= self.observed_at
        ):
            raise ValueError("Las fechas del merge FinOps no son coherentes.")
        return self
