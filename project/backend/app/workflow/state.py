"""Serializable state of one consulting case; no model or provider dependencies."""

from typing import TypedDict

STAGES = {
    1: "engagement_preparation",
    2: "executive_prioritization",
    3: "architecture",
    4: "finops",
    5: "implementation",
    6: "executive_report",
}
TERMINAL = {"completed", "declined", "cancelled"}
OPERATOR_EVENTS = {
    "meeting.completed",
    "deliverable.ready",
    "stage.approved",
    "stage.changes_requested",
    "stage.rejected",
}


class ProcessState(TypedDict):
    case_id: str
    client_id: int | None
    manager_id: str
    stage: int
    iteration: int
    status: str
    revision: int
    artifact_sha256: str
    evidence: list[str]
    rework_cycles: int
    processed: dict[str, str]
    history: list[dict]


def initial_state(case_id, manager_id, client_id=None):
    return ProcessState(
        case_id=case_id,
        client_id=client_id,
        manager_id=manager_id,
        stage=1,
        iteration=1,
        status="awaiting_meeting",
        revision=0,
        artifact_sha256="",
        evidence=[],
        rework_cycles=0,
        processed={},
        history=[],
    )
