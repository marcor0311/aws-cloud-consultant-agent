"""One private receipt per call; delivery only after the audio session closes."""

import hashlib
import hmac
import json
import logging
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request

from src.integrations.access_client import NoRedirects, build_opener

logger = logging.getLogger(__name__)
DEFAULT_OUTBOX = Path(__file__).resolve().parents[4] / "data/post-call"


def now():
    if os.getenv("CALENDAR_ASSISTANT_MODE") == "mock":
        from src.integrations.mock_calendar import MockDateTime

        return MockDateTime.now(timezone.utc).isoformat()
    return datetime.now(timezone.utc).isoformat()


def register_delivery(ctx, session, delivery):
    import asyncio

    async def deliver_after_close():
        await session.aclose()
        await asyncio.to_thread(delivery.finish)

    ctx.add_shutdown_callback(deliver_after_close)


def save(path, body):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as f:
        temporary = Path(f.name)
        json.dump(body, f)
    temporary.chmod(0o600)
    os.replace(temporary, path)


def remember(client, calendar_id, event_id, operation, version, started_at):
    configured = os.getenv("CALENDAR_CALL_RECEIPT_FILE")
    if not configured:
        return False
    save(
        configured,
        {
            "call_id": client.session_id,
            "client_code": client.client_code,
            "email": client.email,
            "calendar_id": calendar_id,
            "calendar_event_id": event_id,
            "operation": operation,
            "version": version,
            "started_at": started_at,
            "completed_at": now(),
        },
    )
    return True


class PostCallDelivery:
    def __init__(self, directory=None):
        self.path = Path(directory or DEFAULT_OUTBOX) / f"{uuid.uuid4().hex}.active"

    def finish(self):
        if not self.path.exists():
            return
        body = json.loads(self.path.read_text())
        body["closed_at"] = now()
        key = os.environ["CALENDAR_ACCESS_SERVICE_KEY"]
        signature = hmac.new(
            key.encode(), json.dumps(body, sort_keys=True).encode(), hashlib.sha256
        ).hexdigest()
        receipt = {"body": body, "signature": signature}
        ready = self.path.with_suffix(".json")
        save(ready, receipt)
        self.path.unlink()
        # Keep the signed receipt for the worker if HTTP fails or the process exits.
        try:
            base = os.environ["CALENDAR_ACCESS_URL"].rstrip("/")
            parsed = urlsplit(base)
            if (
                parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
                or not parsed.hostname
                or (
                    parsed.scheme != "https"
                    and not (
                        parsed.scheme == "http"
                        and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
                    )
                )
            ):
                raise ValueError("Backend de cierre inválido.")
            request = Request(
                base + "/call-ended",
                data=json.dumps(receipt).encode(),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {key}",
                },
                method="POST",
            )
            with build_opener(NoRedirects()).open(request, timeout=4) as response:
                if json.load(response).get("status") == "registered":
                    ready.unlink(missing_ok=True)
        except Exception:
            logger.warning("Post-call receipt retained for worker retry")
