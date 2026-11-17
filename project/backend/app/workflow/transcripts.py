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
    registered = runtime.store.list("meeting")
    same_code = [m for m in registered if m.get("meet_code") == capture["meet_code"]]
    owned = [m for m in same_code if m["manager_id"] == runtime.settings.manager_id]
    scheduled = [m for m in owned if m["status"] == "scheduled"]
    meetings = [
        m
        for m in scheduled
        if timestamp(m["start"]) - 3600 <= began <= timestamp(m["end"]) + 3600
    ]
    if len(meetings) != 1:
        if not registered:
            reason = (
                "No hay reuniones registradas en esta base de workflow. "
                "Primero agendá una cita con el agente; una captura de Meet por sí "
                "sola no registra una cita ni crea un expediente."
            )
        elif not same_code:
            reason = (
                "Ninguna cita registrada tiene el código de Meet de esta captura. "
                "Usá el enlace de la cita agendada y verificá que su registro haya "
                "llegado al backend."
            )
        elif not owned:
            reason = (
                "Las citas con este código de Meet pertenecen a otro operador. "
                "Revisá WORKFLOW_MANAGER_ID en el backend y el worker."
            )
        elif not scheduled:
            reason = (
                "Las citas de este operador y Meet no están en estado scheduled. "
                "Revisá su estado y la sincronización de Calendar."
            )
        elif not meetings:
            reason = (
                "El inicio de la captura está fuera de la ventana de las citas: "
                "debe caer entre una hora antes del inicio y una hora después del final. "
                "Revisá el horario de la cita."
            )
        else:
            reason = (
                "Más de una cita coincide con esta captura. Revisá las citas "
                "duplicadas o superpuestas antes de asociar la transcripción."
            )
        raise ProviderError(
            "capture_requires_one_registered_meeting",
            retry_after=30,
            detail=f"{reason} Registradas={len(registered)}, compatibles={len(meetings)}. "
            "Consultá make meetings. La captura se conserva para reintentar; "
            "make workflow procesa trabajo pendiente, no genera reuniones ficticias.",
        )
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
        # Receipt and generation are separate durable tasks, including without an API key.
        runtime.queue_transcript_preparation(case_id)
