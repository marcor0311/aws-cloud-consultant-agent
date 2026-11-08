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
