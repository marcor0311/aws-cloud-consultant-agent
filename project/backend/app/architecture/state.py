"""Serializable state for architecture design and human approval."""

from typing import TypedDict


class ArchitectureState(TypedDict, total=False):
    case_id: str
    input_id: str
    input_hash: str
    package: dict
    documents: dict[str, str]
    revision: int
    status: str
    decision: str
    feedback: str
    artifact_sha256: str
    handoff: dict
    parent_revision: int | None
    correction_request_id: str
    correction_request: dict
    correction_history: list[dict]
    revision_history: list[dict]
    approval_history: list[dict]
    handoff_history: list[dict]
