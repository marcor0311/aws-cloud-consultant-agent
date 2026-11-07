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
    calendar_event_id: str


def input_hash(transcript: str, query: str) -> str:
    return hashlib.sha256(json.dumps([transcript, query]).encode()).hexdigest()
