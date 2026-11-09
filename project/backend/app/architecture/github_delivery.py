"""Typed GitHub publication boundary orchestrated by Codex through GitHub MCP."""

import base64
import hashlib
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class GitHubContract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class GitHubFile(GitHubContract):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    path: str = Field(min_length=1, max_length=500)
    encoding: Literal["utf-8", "base64"]
    content: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def path_and_hash_are_valid(self):
        if (
            not self.path.startswith("docs/03-architecture/versions/v")
            or ".." in self.path
        ):
            raise ValueError(
                "Los archivos deben pertenecer a la revisión de Arquitectura."
            )
        try:
            raw = (
                self.content.encode("utf-8")
                if self.encoding == "utf-8"
                else base64.b64decode(self.content, validate=True)
            )
        except ValueError as error:
            raise ValueError("El contenido base64 no es válido.") from error
        if hashlib.sha256(raw).hexdigest() != self.sha256:
            raise ValueError("El SHA-256 del archivo GitHub no coincide.")
        return self


class GitHubPublicationPlan(GitHubContract):
    contract_version: Literal["1.0"] = "1.0"
    case_id: str = Field(min_length=1, max_length=120)
    project_id: str = Field(min_length=1, max_length=120)
    revision: int = Field(ge=1)
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    repository_url: str = Field(pattern=r"^https://github\.com/[^/]+/[^/]+$")
    source_issue_url: str = Field(
        pattern=r"^https://github\.com/[^/]+/[^/]+/issues/[0-9]+$"
    )
    base_branch: Literal["main"] = "main"
    base_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    branch: str = Field(pattern=r"^agent3/[a-z0-9][a-z0-9-]*/architecture-v[0-9]{3}$")
    commit_message: str = Field(min_length=1, max_length=200)
    pull_request_title: str = Field(min_length=1, max_length=200)
    pull_request_body: str = Field(min_length=1, max_length=10000)
    files: list[GitHubFile] = Field(min_length=1, max_length=200)


class GitHubPullRequestReceipt(GitHubContract):
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


class GitHubApprovalReceipt(GitHubContract):
    contract_version: Literal["1.0"] = "1.0"
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    pull_request_url: str = Field(
        pattern=r"^https://github\.com/[^/]+/[^/]+/pull/[0-9]+$"
    )
    head_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    decision: Literal["approved"]
    reviewer: str = Field(min_length=1, max_length=200)
    review_id: str = Field(min_length=1, max_length=200)
    reviewed_at: AwareDatetime
    merge_commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    source_issue_url: str = Field(
        pattern=r"^https://github\.com/[^/]+/[^/]+/issues/[0-9]+$"
    )
    source_issue_state: Literal["closed"]
    source_issue_closed_at: AwareDatetime


class GitHubFinOpsIssueReceipt(GitHubContract):
    contract_version: Literal["1.0"] = "1.0"
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    issue_url: str = Field(pattern=r"^https://github\.com/[^/]+/[^/]+/issues/[0-9]+$")
    issue_number: int = Field(ge=1)
    created_at: AwareDatetime
    body_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    assignees: list[str] = Field(min_length=1, max_length=20)
