"""Ingest browser captions without Google transcript licensing or inline inference."""

import hashlib
import json
import re
import uuid

from app.integrations.errors import ConfigurationError, ProviderError
from app.workflow.runtime import timestamp


def receive_capture(runtime, body):
    if not isinstance(body, dict) or set(body) != {
        "capture_id",
        "meeting_url",
        "started_at",
        "ended_at",
        "reporter_name",
        "segments",
    }:
        raise ValueError("capture_fields")
    for field in (
        "capture_id",
        "meeting_url",
        "started_at",
        "ended_at",
        "reporter_name",
    ):
        if not isinstance(body[field], str) or len(body[field]) > 512:
            raise ValueError("capture_field")
    if str(uuid.UUID(body["capture_id"])) != body["capture_id"]:
        raise ValueError("capture_id")
    match = re.fullmatch(
        r"https://meet\.google\.com/(?:meet/)?([a-z]{3}-[a-z]{4}-[a-z]{3})",
        body["meeting_url"],
    )
    if not match:
        raise ValueError("meeting_url")
    began, ended = timestamp(body["started_at"]), timestamp(body["ended_at"])
    if not 0 < ended - began <= 86400 or ended > runtime.store.clock() + 300:
        raise ValueError("capture_interval")
    segments = body["segments"]
    if not isinstance(segments, list) or not 1 <= len(segments) <= 10000:
        raise ValueError("capture_segments")
    size, previous = 0, began - 5
    for segment in segments:
        if not isinstance(segment, dict) or set(segment) != {"speaker", "at", "text"}:
            raise ValueError("segment_fields")
        if any(not isinstance(segment[k], str) for k in segment):
            raise ValueError("segment_type")
        if (
            not 1 <= len(segment["speaker"].strip()) <= 200
            or not segment["text"].strip()
        ):
            raise ValueError("segment_speaker_or_text")
        at = timestamp(segment["at"])
        if not previous <= at <= ended + 5:
            raise ValueError("segment_interval")
        previous = at
        size += len(segment["text"])
    if size > 200000:
        raise ValueError("transcript_requires_chunking")
    key = f"capture:{body['capture_id']}"
    digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    payload = {**body, "meet_code": match[1], "digest": digest}
    with runtime.store.lock(key):
        existing = runtime.store.job(key)
        if existing:
            if existing["payload"]["digest"] != digest:
                raise ValueError("capture_id_reused")
            return {"status": "duplicate", "task_id": key}
        runtime.store.receive(key, "captured_transcript", payload)
    return {"status": "accepted", "task_id": key}


def process_capture(runtime, capture, job_id):
    began, ended = timestamp(capture["started_at"]), timestamp(capture["ended_at"])
    meetings = [
        m
        for m in runtime.store.list("meeting")
        if m.get("meet_code") == capture["meet_code"]
        and m["manager_id"] == runtime.settings.manager_id
        and m["status"] == "scheduled"
        and timestamp(m["start"]) - 3600 <= began <= timestamp(m["end"]) + 3600
    ]
    if len(meetings) != 1:
        raise ProviderError("capture_requires_one_registered_meeting", retry_after=30)
    meeting = meetings[0]
    case_id = meeting["case_id"]
    with runtime.store.lock(f"capture-case:{case_id}"):
        previous = runtime.store.get(f"transcript:{case_id}")
        if previous and previous.get("capture_id") != capture["capture_id"]:
            raise ConfigurationError("transcript_requires_reconciliation")
        text = "\n".join(
            f"[{s['at']}] {s['speaker']}: {s['text']}" for s in capture["segments"]
        )
        runtime.store.put(
            f"transcript:{case_id}",
            "transcript",
            {
                "case_id": case_id,
                "capture_id": capture["capture_id"],
                "source": "transcriptonic_captions",
                "meeting_url": capture["meeting_url"],
                "started_at": capture["started_at"],
                "ended_at": capture["ended_at"],
                "reporter_name": capture["reporter_name"],
                "completion_evidence": "browser_capture_ended",
                "segments": capture["segments"],
                "text": text,
            },
        )
        runtime.process.ensure(case_id, meeting["client_id"])
        runtime.process.internal(
            case_id, f"transcript.available:{job_id}", "transcript.available"
        )
        runtime.store.event(
            f"processed:{job_id}",
            case_id,
            "transcript.processed",
            {
                "source": "transcriptonic_captions",
                "capture_id": capture["capture_id"],
                "capture_seconds": ended - began,
            },
        )
        # Captions are saved even before the preparation model is configured.
        if runtime.settings.mode == "mock" or (
            runtime.settings.openai_key and runtime.settings.openai_model
        ):
            runtime.submit_preparation(
                case_id, "start", event_id=job_id, transcript=text, query=text
            )
        else:
            runtime.store.event(
                f"configuration:{job_id}", case_id, "preparation.configuration_required"
            )
