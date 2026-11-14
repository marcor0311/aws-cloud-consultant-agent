"""Serializable preparation state and stable input identity."""

import hashlib
import json
from datetime import datetime, timezone
from typing import TypedDict


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PreparationState(TypedDict, total=False):
    case_id: str
    event_id: str
    input_hash: str
    transcript: str
    meeting_notes: str
    query: str
    references: list[dict]
    draft: str
    revision: int
    feedback: str
    decision: str
    accepted_at: str
    handed_off_at: str
    search_seconds: float
    status: str
    handoff: dict
    package: dict
    review_subject: str
    presentation_approval: dict
    calendar_event_id: str


def input_hash(transcript: str, query: str, meeting_notes: str = "") -> str:
    # Preserve the identity of checkpoints created before notes were supported.
    inputs = [transcript, query]
    if meeting_notes:
        inputs.append(meeting_notes)
    return hashlib.sha256(json.dumps(inputs).encode()).hexdigest()


def meeting_sources(state: PreparationState) -> dict[str, str]:
    return {
        "transcript": state["transcript"],
        "meeting_notes": state.get("meeting_notes", ""),
    }


def meeting_documents(state: PreparationState) -> dict[str, str]:
    documents = {"meeting-transcript.md": state["transcript"]}
    if state.get("meeting_notes"):
        documents["meeting-notes.md"] = state["meeting_notes"]
    return documents
