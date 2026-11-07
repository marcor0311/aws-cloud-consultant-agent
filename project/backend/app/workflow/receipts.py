"""Validate receipts from the trusted voice tool after its OTP session is closed."""

import hashlib
import hmac
import json

from app.workflow.runtime import timestamp


def accept_call_receipt(runtime, receipt, key, lookup):
    body = receipt.get("body", {})
    expected = hmac.new(
        key.encode(), json.dumps(body, sort_keys=True).encode(), hashlib.sha256
    ).hexdigest()
    if len(key) < 32 or not hmac.compare_digest(
        expected, str(receipt.get("signature", ""))
    ):
        raise ValueError("Firma de cierre inválida.")
    required = {
        "call_id",
        "client_code",
        "email",
        "calendar_id",
        "calendar_event_id",
        "operation",
        "version",
        "started_at",
        "completed_at",
        "closed_at",
    }
    if set(body) != required or any(
        not isinstance(body[k], str) or len(body[k]) > 512
        for k in required - {"started_at"}
    ):
        raise ValueError("Recibo de cierre inválido.")
    if (
        not body["call_id"]
        or not body["calendar_event_id"]
        or body["operation"] not in {"scheduled", "rescheduled", "cancelled"}
    ):
        raise ValueError("Referencia de cita inválida.")
    if timestamp(body["closed_at"]) < timestamp(body["completed_at"]):
        raise ValueError("La llamada todavía no había terminado.")
    if (
        body["started_at"] is not None
        and not 0
        <= timestamp(body["completed_at"]) - timestamp(body["started_at"])
        <= 3600
    ):
        raise ValueError("Intervalo de agenda inválido.")
    client = lookup(body["client_code"])
    if not client or not client.enabled or client.company_email != body["email"]:
        raise ValueError("Cliente no autorizado.")
    receipt_key = f"call-receipt:{body['call_id']}"
    digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    with runtime.store.lock(receipt_key):
        previous = runtime.store.get(receipt_key)
        if previous:
            if previous["digest"] != digest:
                raise ValueError("La llamada ya tiene otro resultado final.")
            return {"status": "registered", "case_id": previous["case_id"]}
        payload = {
            k: body[k]
            for k in (
                "calendar_id",
                "calendar_event_id",
                "operation",
                "version",
                "started_at",
                "completed_at",
            )
        }
        if body["started_at"] is None:
            payload.pop("started_at")
            payload.pop("completed_at")
        result = runtime.register_meeting(payload, client.client_id)
        runtime.store.put(
            receipt_key,
            "call_receipt",
            {
                "digest": digest,
                "case_id": result["case_id"],
                "closed_at": body["closed_at"],
            },
        )
        runtime.store.event(
            f"call-closed:{body['call_id']}",
            result["case_id"],
            "call.closed",
            {"closed_at": body["closed_at"]},
        )
        return result
