"""Calendar channel management and incremental sync, independent of voice sessions."""

import hmac
import secrets
import uuid
from urllib.parse import urlsplit

from app.integrations.errors import ProviderError


class CalendarSync:
    def __init__(self, runtime):
        self.runtime = runtime
        self.store, self.google = runtime.store, runtime.google

    def subscribe(self):
        settings = self.runtime.settings
        address = urlsplit(settings.calendar_webhook_url)
        if (
            address.scheme != "https"
            or not address.hostname
            or address.username
            or address.query
            or address.fragment
        ):
            raise ValueError(
                "Configurar WORKFLOW_CALENDAR_WEBHOOK_URL con el endpoint HTTPS público."
            )
        calendar_id = settings.calendar_id
        with self.store.lock(f"calendar-watch:{calendar_id}"):
            active = [
                c
                for c in self.store.list("calendar_channel")
                if c["calendar_id"] == calendar_id
                and c.get("expiration", 0) > self.store.clock() + 3600
                and c["address"] == settings.calendar_webhook_url
            ]
            if active:
                return {"status": "active", "expires_at": active[0]["expiration"]}
            channel = {
                "id": str(uuid.uuid4()),
                "token": secrets.token_urlsafe(32),
                "calendar_id": calendar_id,
                "address": settings.calendar_webhook_url,
                "resource_id": "",
                "expiration": self.store.clock() + 300,
            }
            key = f"calendar-channel:{channel['id']}"
            # Google's initial sync notification can arrive before watch returns.
            self.store.put(key, "calendar_channel", channel)
            result = self.google.watch_calendar(
                calendar_id, channel["id"], channel["token"], channel["address"]
            )
            channel.update(
                resource_id=result["resourceId"],
                expiration=int(result["expiration"]) / 1000,
            )
            self.store.put(key, "calendar_channel", channel)
            self.store.receive(
                f"calendar-initial:{channel['id']}",
                "calendar_sync",
                {"calendar_id": calendar_id},
            )
            return {"status": "subscribed", "expires_at": channel["expiration"]}

    def receive(self, headers):
        channel = self.store.get(
            f"calendar-channel:{headers.get('x-goog-channel-id', '')}"
        )
        if not channel or channel["expiration"] <= self.store.clock():
            raise ValueError("Canal de Calendar desconocido o vencido.")
        if not hmac.compare_digest(
            channel["token"], headers.get("x-goog-channel-token", "")
        ):
            raise ValueError("Token de Calendar inválido.")
        resource = headers.get("x-goog-resource-id", "")
        state = headers.get("x-goog-resource-state", "")
        number = headers.get("x-goog-message-number", "")
        if (
            not resource
            or not number.isdigit()
            or len(number) > 30
            or state not in {"sync", "exists", "not_exists"}
        ):
            raise ValueError("Notificación de Calendar inválida.")
        if channel["resource_id"] and resource != channel["resource_id"]:
            raise ValueError("Recurso de Calendar inválido.")
        if not channel["resource_id"] and state != "sync":
            raise ValueError("El canal todavía no está confirmado.")
        received = self.store.receive(
            f"calendar-notice:{channel['id']}:{number}",
            "calendar_sync",
            {"calendar_id": channel["calendar_id"]},
        )
        return {"status": "accepted" if received else "duplicate"}

    def sync(self, calendar_id):
        with self.store.lock(f"calendar-sync:{calendar_id}"):
            key = f"calendar-sync:{calendar_id}"
            cursor = self.store.get(key) or {}
            token, page, seen = cursor.get("sync_token", ""), "", set()
            while True:
                try:
                    result = self.google.calendar_changes(calendar_id, token, page)
                except ProviderError as error:
                    if str(error) != "google_http_410" or not token:
                        raise
                    token, page, seen = "", "", set()
                    continue
                for event in result.get("items", []):
                    case_id = str(
                        uuid.uuid5(uuid.NAMESPACE_URL, f"{calendar_id}:{event['id']}")
                    )
                    meeting = self.store.get(f"meeting:{case_id}")
                    # Never start a project from an unregistered invitation. It may still be in a call.
                    if not meeting:
                        continue
                    payload = {
                        "calendar_id": calendar_id,
                        "calendar_event_id": event["id"],
                        "operation": "cancelled"
                        if event.get("status") == "cancelled"
                        else "rescheduled",
                        "version": event.get("etag", event.get("updated", "")),
                    }
                    self.runtime.register_meeting(payload, meeting["client_id"])
                page = result.get("nextPageToken", "")
                if not page:
                    if not result.get("nextSyncToken"):
                        raise ProviderError("calendar_sync_token_missing")
                    self.store.put(
                        key,
                        "calendar_sync",
                        {
                            "calendar_id": calendar_id,
                            "sync_token": result["nextSyncToken"],
                        },
                    )
                    return
                if page in seen:
                    raise ProviderError("google_pagination_loop")
                seen.add(page)
