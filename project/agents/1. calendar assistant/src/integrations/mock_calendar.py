"""Local Calendar stand-in shared with the offline demo through a SQLite fixture."""

# Google API keyword names are part of the adapter's compatibility contract.
# ruff: noqa: N803

import hashlib
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path


class MockDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        path = Path(os.environ["MOCK_CLOCK_FILE"])
        return cls.fromtimestamp(json.loads(path.read_text())["timestamp"], tz=tz)


class MockRequest:
    def __init__(self, action):
        self.action = action
        self.headers = {}

    def execute(self):
        return self.action()


class MockCalendar:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS mock_calendar_events (id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )

    def events(self):
        return self

    def freebusy(self):
        return self

    def _all(self):
        with sqlite3.connect(self.path) as db:
            return [
                json.loads(row[0])
                for row in db.execute("SELECT payload FROM mock_calendar_events")
            ]

    def _get(self, event_id):
        return next(event for event in self._all() if event["id"] == event_id)

    def _save(self, event):
        with sqlite3.connect(self.path) as db:
            db.execute(
                "INSERT INTO mock_calendar_events(id,payload) VALUES (?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
                (event["id"], json.dumps(event)),
            )
        return event

    def insert(self, *, calendarId, body, sendUpdates, conferenceDataVersion=0):
        def action():
            if conferenceDataVersion != 1 or sendUpdates != "all":
                raise ValueError("La demo espera una invitación con Meet.")
            seed = hashlib.sha256(body["id"].encode()).digest()
            letters = "".join(chr(97 + value % 26) for value in seed[:10])
            code = f"{letters[:3]}-{letters[3:7]}-{letters[7:]}"
            return self._save(
                {
                    **body,
                    "status": "confirmed",
                    "etag": '"mock-v1"',
                    "organizer": {"email": "stuart@consultora.example", "self": True},
                    "htmlLink": f"https://calendar.example/mock/{body['id']}",
                    "hangoutLink": f"https://meet.example/mock/{code}",
                    "conferenceData": {**body["conferenceData"], "conferenceId": code},
                    "is_mock": True,
                }
            )

        return MockRequest(action)

    def query(self, *, body):
        def action():
            start, end = (
                datetime.fromisoformat(body["timeMin"]),
                datetime.fromisoformat(body["timeMax"]),
            )
            busy = [
                {"start": event["start"]["dateTime"], "end": event["end"]["dateTime"]}
                for event in self._all()
                if event.get("status") != "cancelled"
                and datetime.fromisoformat(event["start"]["dateTime"]) < end
                and datetime.fromisoformat(event["end"]["dateTime"]) > start
            ]
            return {"calendars": {item["id"]: {"busy": busy} for item in body["items"]}}

        return MockRequest(action)

    def list(self, *, calendarId, timeMin, timeMax, **kwargs):
        def action():
            start, end = (
                datetime.fromisoformat(timeMin),
                datetime.fromisoformat(timeMax),
            )
            return {
                "items": [
                    e
                    for e in self._all()
                    if e.get("status") != "cancelled"
                    and start <= datetime.fromisoformat(e["start"]["dateTime"]) < end
                ]
            }

        return MockRequest(action)

    def get(self, *, calendarId, eventId):
        return MockRequest(lambda: self._get(eventId))

    def patch(self, *, calendarId, eventId, body, **kwargs):
        return MockRequest(
            lambda: self._save({**self._get(eventId), **body, "etag": '"mock-v2"'})
        )

    def delete(self, *, calendarId, eventId, **kwargs):
        def action():
            self._save({**self._get(eventId), "status": "cancelled"})
            return ""

        return MockRequest(action)
