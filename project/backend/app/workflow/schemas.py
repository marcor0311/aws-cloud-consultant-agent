"""Operator event contract shared by HTTP and MCP; identity comes from the server."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ProcessEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    event_id: str = Field(min_length=1, max_length=120)
    kind: Literal[
        "meeting.completed",
        "deliverable.ready",
        "stage.approved",
        "stage.changes_requested",
        "stage.rejected",
    ]
    stage: int = Field(ge=1, le=6)
    iteration: int = Field(ge=1)
    revision: int = Field(default=0, ge=0)
    artifact_sha256: str = Field(default="", pattern=r"^([a-f0-9]{64})?$")
    evidence: list[str] = Field(default_factory=list, max_length=30)
    comment: str = Field(default="", max_length=4000)
