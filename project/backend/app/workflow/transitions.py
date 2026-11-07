"""Business transitions: known events advance stages without asking a model."""

import hashlib
import json
import re

from app.workflow.state import TERMINAL


def fingerprint(event):
    # Delivery time is assigned on receipt; it is not part of the event identity.
    payload = {k: v for k, v in event.items() if k != "at"}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def require_artifact(event):
    if (
        type(event.get("revision")) is not int
        or event["revision"] < 1
        or not re.fullmatch(r"[a-f0-9]{64}", event.get("artifact_sha256", ""))
        or not event.get("evidence")
        or not all(isinstance(e, str) and e.strip() for e in event["evidence"])
    ):
        raise ValueError("Indicar versión, SHA-256 y referencias del entregable.")


def transition(state, event):
    """Pure validation also runs before enqueue and again at worker execution."""
    if state["status"] in TERMINAL:
        raise ValueError("El proceso ya terminó.")
    if (event["stage"], event["iteration"]) != (state["stage"], state["iteration"]):
        raise ValueError("La etapa o su iteración cambió; consultar el proceso actual.")
    kind, stage, status = event["kind"], state["stage"], state["status"]
    internal = event.get("origin") == "internal"
    result = dict(state)

    if kind == "meeting.completed" and stage == 1 and status == "awaiting_meeting":
        result["status"] = "awaiting_transcript"
    elif (
        kind == "meeting.cancelled"
        and internal
        and stage == 1
        and status in {"awaiting_meeting", "awaiting_transcript"}
    ):
        result["status"] = "cancelled"
    elif (
        kind == "transcript.available"
        and internal
        and stage == 1
        and status in {"awaiting_meeting", "awaiting_transcript"}
    ):
        # A completed conference with a usable transcript is sufficient evidence.
        result["status"] = "preparing"
    elif (
        kind == "preparation.revision_requested"
        and internal
        and stage == 1
        and status == "awaiting_review"
        and event.get("revision") == state["revision"]
        and event.get("artifact_sha256") == state["artifact_sha256"]
    ):
        result["status"] = "preparing"
        result["rework_cycles"] = state["rework_cycles"] + 1
    elif (
        kind in {"preparation.ready", "deliverable.ready"}
        and (
            (kind == "preparation.ready" and internal and stage == 1)
            or (kind == "deliverable.ready" and stage > 1)
        )
        and status in {"preparing", "awaiting_deliverable", "awaiting_review"}
    ):
        require_artifact(event)
        if event["revision"] <= state["revision"]:
            raise ValueError("El entregable requiere una versión nueva.")
        result.update(
            status="awaiting_review",
            revision=event["revision"],
            artifact_sha256=event["artifact_sha256"],
            evidence=event["evidence"],
        )
    elif (kind == "preparation.approved" and internal and stage == 1) or (
        kind == "stage.approved" and stage > 1
    ):
        if (
            status != "awaiting_review"
            or event.get("revision") != state["revision"]
            or event.get("artifact_sha256") != state["artifact_sha256"]
        ):
            raise ValueError("Aprobar únicamente la versión pendiente exacta.")
        if stage == 6:
            result["status"] = "completed"
        else:
            result.update(stage=stage + 1, iteration=state["iteration"] + 1)
            if stage == 1:
                # Direction reviews the package approved by the Engagement Manager.
                result["status"] = "awaiting_review"
            else:
                result.update(
                    status="awaiting_deliverable",
                    revision=0,
                    artifact_sha256="",
                    evidence=[],
                )
    elif (
        kind in {"stage.changes_requested", "stage.rejected"}
        and stage > 1
        and status == "awaiting_review"
    ):
        if (
            not event.get("comment", "").strip()
            or event.get("revision") != state["revision"]
            or event.get("artifact_sha256") != state["artifact_sha256"]
        ):
            raise ValueError("Indicar la versión exacta y el motivo de la decisión.")
        if kind == "stage.rejected":
            if stage != 2:
                raise ValueError("Solo dirección puede rechazar el proyecto.")
            result["status"] = "declined"
        else:
            result.update(
                stage=3 if stage == 4 else stage,
                iteration=state["iteration"] + 1,
                status="awaiting_deliverable",
                revision=0,
                artifact_sha256="",
                evidence=[],
                rework_cycles=state["rework_cycles"] + 1,
            )
    else:
        raise ValueError("El evento no corresponde al estado actual.")

    result["processed"] = {**state["processed"], event["event_id"]: fingerprint(event)}
    result["history"] = [
        *state["history"],
        {
            **event,
            "from_stage": stage,
            "to_stage": result["stage"],
            "from_iteration": state["iteration"],
            "to_iteration": result["iteration"],
            "status": result["status"],
        },
    ]
    return result
