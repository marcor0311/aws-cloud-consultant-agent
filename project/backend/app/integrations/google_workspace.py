"""External adapters. No credentials or transcript bodies in error messages."""

import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import httpx
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from app.integrations.errors import ConfigurationError, ProviderError


class GoogleWorkspace:
    def __init__(self, token_file, client=None):
        self.token_file = token_file
        self.client = client or httpx.Client(timeout=30)
        self.credentials = None

    def request(self, method, url, **kwargs):
        if not self.token_file or not self.token_file.is_file():
            raise ConfigurationError("authorize_workflow_google_account")
        if self.credentials is None:
            self.credentials = Credentials.from_authorized_user_file(
                str(self.token_file)
            )
        if not self.credentials.valid:
            self.credentials.refresh(Request())
        try:
            response = self.client.request(
                method,
                url,
                headers={"Authorization": f"Bearer {self.credentials.token}"},
                **kwargs,
            )
        except httpx.HTTPError:
            raise ProviderError("google_transport_error") from None
        if response.status_code not in {200, 201, 204}:
            if response.status_code in {401, 403}:
                raise ConfigurationError("google_access_denied")
            raise ProviderError(f"google_http_{response.status_code}")
        return response.json() if response.content else {}

    def pages(self, url, field, **params):
        result, seen = [], set()
        while True:
            payload = self.request("GET", url, params=params)
            result.extend(payload.get(field, []))
            token = payload.get("nextPageToken")
            if not token:
                return result
            if token in seen:
                raise ProviderError("google_pagination_loop")
            seen.add(token)
            params["pageToken"] = token

    def calendar_event(self, calendar_id, event_id):
        return self.request(
            "GET",
            "https://www.googleapis.com/calendar/v3/calendars/"
            f"{quote(calendar_id, safe='')}/events/{quote(event_id, safe='')}",
        )

    def calendar_events(self, calendar_id):
        now = datetime.now(timezone.utc)
        return self.pages(
            "https://www.googleapis.com/calendar/v3/calendars/"
            f"{quote(calendar_id, safe='')}/events",
            "items",
            singleEvents="true",
            privateExtendedProperty="calendar_assistant=stuart",
            timeMin=(now - timedelta(days=29)).isoformat(),
            timeMax=(now + timedelta(days=15)).isoformat(),
            maxResults=250,
        )

    def watch_calendar(self, calendar_id, channel_id, token, address):
        return self.request(
            "POST",
            f"https://www.googleapis.com/calendar/v3/calendars/{quote(calendar_id, safe='')}/events/watch",
            json={
                "id": channel_id,
                "type": "web_hook",
                "token": token,
                "address": address,
                "params": {"ttl": "604800"},
            },
        )

    def calendar_changes(self, calendar_id, sync_token="", page_token=""):
        params = {"maxResults": 250, "showDeleted": "true"}
        if sync_token:
            params["syncToken"] = sync_token
        if page_token:
            params["pageToken"] = page_token
        return self.request(
            "GET",
            f"https://www.googleapis.com/calendar/v3/calendars/{quote(calendar_id, safe='')}/events",
            params=params,
        )

    def space(self, code):
        if not re.fullmatch(r"[a-z]{3}-[a-z]{4}-[a-z]{3}", code):
            raise ValueError("Código de Meet inválido.")
        return self.request("GET", f"https://meet.googleapis.com/v2/spaces/{code}")

    def subscribe(self, space_name, topic):
        return self.request(
            "POST",
            "https://workspaceevents.googleapis.com/v1/subscriptions",
            json={
                "targetResource": f"//meet.googleapis.com/{space_name}",
                "eventTypes": ["google.workspace.meet.transcript.v2.fileGenerated"],
                "notificationEndpoint": {"pubsubTopic": topic},
                "payloadOptions": {"includeResource": False},
                "ttl": "86400s",
            },
        )

    def find_subscriptions(self, space_name):
        return self.pages(
            "https://workspaceevents.googleapis.com/v1/subscriptions",
            "subscriptions",
            filter=f'event_types:"google.workspace.meet.transcript.v2.fileGenerated" AND target_resource="//meet.googleapis.com/{space_name}"',
        )

    def conferences(self, space_name):
        return self.pages(
            "https://meet.googleapis.com/v2/conferenceRecords",
            "conferenceRecords",
            filter=f'space.name = "{space_name}"',
            pageSize=100,
        )

    def transcripts(self, conference_name):
        return self.pages(
            f"https://meet.googleapis.com/v2/{conference_name}/transcripts",
            "transcripts",
        )

    def operation(self, name):
        if not re.fullmatch(r"operations/[A-Za-z0-9_=-]+", name):
            raise ValueError("Operación Google inválida.")
        return self.request("GET", f"https://workspaceevents.googleapis.com/v1/{name}")

    def renew(self, subscription):
        name = subscription["name"]
        if not re.fullmatch(r"subscriptions/[A-Za-z0-9_=-]+", name):
            raise ValueError("Suscripción inválida.")
        return self.request(
            "PATCH",
            f"https://workspaceevents.googleapis.com/v1/{name}",
            params={"updateMask": "ttl"},
            json={"name": name, "ttl": "86400s"},
        )

    def transcript(self, transcript_name):
        if not re.fullmatch(
            r"conferenceRecords/[A-Za-z0-9_-]+/transcripts/[A-Za-z0-9_-]+",
            transcript_name,
        ):
            raise ValueError("Recurso de transcripción inválido.")
        conference_name = transcript_name.split("/transcripts/")[0]
        base = "https://meet.googleapis.com/v2/"
        conference = self.request("GET", base + conference_name)
        if not conference.get("endTime"):
            raise ProviderError("conference_still_running", retry_after=60)
        transcripts = self.pages(base + conference_name + "/transcripts", "transcripts")
        if not transcripts or any(
            t.get("state") != "FILE_GENERATED" for t in transcripts
        ):
            raise ProviderError("transcript_not_ready", retry_after=60)
        entries = []
        for transcript in transcripts:
            entries.extend(
                self.pages(base + transcript["name"] + "/entries", "transcriptEntries")
            )
        entries.sort(key=lambda item: (item.get("startTime", ""), item.get("name", "")))
        text = "\n".join(
            f"[{e.get('startTime', '')}] {e.get('participant', 'speaker')}: {e.get('text', '')}"
            for e in entries
            if e.get("text", "").strip()
        )
        if not text.strip():
            raise ProviderError("transcript_empty")
        if len(text) > 200_000:
            raise ConfigurationError("transcript_requires_chunking")
        return {
            "conference": conference,
            "text": text,
            "sources": [t["name"] for t in transcripts],
        }

    def pull(self, subscription):
        if not re.fullmatch(r"projects/[^/]+/subscriptions/[^/]+", subscription):
            raise ValueError("Suscripción Pub/Sub inválida.")
        return self.request(
            "POST",
            f"https://pubsub.googleapis.com/v1/{subscription}:pull",
            json={"maxMessages": 10},
        ).get("receivedMessages", [])

    def acknowledge(self, subscription, ack_ids):
        return self.request(
            "POST",
            f"https://pubsub.googleapis.com/v1/{subscription}:acknowledge",
            json={"ackIds": ack_ids},
        )
