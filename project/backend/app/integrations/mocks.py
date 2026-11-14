"""Offline providers and a persistent simulated clock. Never call external services."""

import hashlib
import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import BACKEND_DIR
from app.preparation.models import ExecutivePackage

FIXTURES = BACKEND_DIR / "fixtures/preparation"


def load_projects():
    projects = json.loads((FIXTURES / "projects.json").read_text())
    return [
        {**p, "transcript": (FIXTURES / p["transcript_file"]).read_text()}
        for p in projects
    ]


class MockClock:
    def __init__(self, directory):
        self.path = Path(directory) / "mock-clock.json"
        self.lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not self.path.exists():
            self._write(datetime.fromisoformat("2026-11-06T08:00:00-06:00").timestamp())

    def _write(self, value):
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"timestamp": value, "is_simulated": True}))
        os.replace(temporary, self.path)

    def __call__(self):
        with self.lock:
            return json.loads(self.path.read_text())["timestamp"]

    def advance(self, seconds):
        if seconds < 0:
            raise ValueError("El reloj simulado no retrocede.")
        with self.lock:
            self._write(self() + seconds)

    def move_to(self, value):
        self.advance(max(0, value - self()))


class MockWorkspace:
    def __init__(self, store, directory):
        self.store = store
        self.calendar_file = Path(directory) / "mock-calendar.sqlite3"

    def calendar_events(self, _calendar_id):
        if not self.calendar_file.exists():
            return []
        with sqlite3.connect(self.calendar_file) as db:
            rows = db.execute("SELECT payload FROM mock_calendar_events").fetchall()
        return [json.loads(row[0]) for row in rows]

    def calendar_event(self, calendar_id, event_id):
        rows = [e for e in self.calendar_events(calendar_id) if e["id"] == event_id]
        if len(rows) != 1:
            raise ValueError("La reserva ficticia todavía no existe.")
        return rows[0]

    def space(self, code):
        return {"name": f"spaces/mock-{code}"}

    def find_subscriptions(self, space):
        return [s for s in self.store.list("mock_subscription") if s["space"] == space]

    def subscribe(self, space, topic):
        key = uuid.uuid5(uuid.NAMESPACE_URL, space).hex
        result = {
            "name": f"subscriptions/mock-{key}",
            "space": space,
            "notificationEndpoint": {"pubsubTopic": topic},
            "expireTime": datetime.fromtimestamp(
                self.store.clock() + 86400, timezone.utc
            ).isoformat(),
        }
        self.store.put(f"mock-subscription:{space}", "mock_subscription", result)
        return {"done": True, "response": result}

    def renew(self, subscription):
        return self.subscribe(
            subscription["space"], subscription["notificationEndpoint"]["pubsubTopic"]
        )

    def transcript(self, transcript_name):
        conference = transcript_name.split("/transcripts/")[0]
        result = self.store.get(f"mock-meeting:{conference}")
        if not result:
            raise ValueError("La reunión ficticia todavía no ha terminado.")
        return result

    def conferences(self, space):
        return [
            m["conference"]
            for m in self.store.list("mock_meeting")
            if m["conference"]["space"] == space
        ]

    def transcripts(self, conference):
        return [
            {
                "name": f"{conference}/transcripts/mock-transcript",
                "state": "FILE_GENERATED",
            }
        ]

    def pull(self, _subscription):
        return []

    def acknowledge(self, *_):
        return {}


class MockSlack:
    def __init__(self, store, manager_id):
        self.store, self.manager_id = store, manager_id

    def send(self, notice, notification_id):
        artifact = self.store.get(f"artifact:{notice['case_id']}:{notice['revision']}")
        if (
            not artifact
            or not {"meeting-transcript.md", "executive-summary.md", "presentation.md"}
            <= artifact["documents"].keys()
        ):
            raise ValueError("No avisar a Stuart antes de guardar todos los insumos.")
        project = next(
            (
                p
                for p in self.store.project_list(self.manager_id)
                if p["case_id"] == notice["case_id"]
            ),
            {},
        )
        title = project.get("title", notice["case_id"])
        if notice["status"] == "awaiting_review":
            text = (
                f"Stuart, el guion de {title} está listo para revisión, basado en la presentación aprobada."
                if artifact.get("presentation_approval")
                else (
                    f"Stuart, ya preparé los insumos de {title}: transcripción, resumen, ideas para "
                    "la presentación. Cuando te sirva, abrí ChatGPT, invocá "
                    "el agente de preparación y elegí este proyecto. Trabajemos sobre los borradores."
                )
            )
        else:
            text = f"El paquete de {title}, revisión {notice['revision']}, quedó aprobado para la siguiente etapa."
        receipt = {"channel": "MOCK-DM-STUART", "ts": notification_id}
        self.store.put(
            f"mock-slack:{notification_id}",
            "mock_slack",
            {
                **receipt,
                **notice,
                "text": text,
                "sent_at": self.store.clock(),
                "is_mock": True,
            },
        )
        return receipt


class MockPreparer:
    def __init__(self, references, store, clock):
        self.references, self.store, self.clock = references, store, clock
        self.by_hash = {
            hashlib.sha256(p["transcript"].encode()).hexdigest(): p
            for p in load_projects()
        }

    def __call__(self, state):
        project = self.by_hash.get(
            hashlib.sha256(state["transcript"].encode()).hexdigest()
        )
        if not project:
            raise ValueError(
                "El modelo mock admite las transcripciones ficticias de la demo."
            )
        matches = self.references.search(project["search_query"])
        selected = [r for r in matches if r["project_id"] == project["reference_id"]]
        if not selected:
            raise ValueError("El antecedente esperado no apareció en la búsqueda SQL.")
        reference = self.references.read_reference(project["reference_id"])
        document = next(
            d for d in reference["documents"] if d["path"].endswith("project-brief.md")
        )
        sources = {
            "transcript": state["transcript"],
            **{d["path"]: d["content"] for d in reference["documents"]},
        }

        def finding(item):
            return {
                "text": item["text"],
                "status": item.get("status", "confirmed"),
                "citations": [{"source_id": "transcript", "quote": item["quote"]}],
            }

        payload = state.get("package") or {
            "summary": project["summary"],
            "needs": [finding(i) for i in project["needs"]],
            "requirements": [finding(i) for i in project["requirements"]],
            "budget": finding(project["budget"]),
            "timeline": finding(project["timeline"]),
            "risks": [
                {
                    "text": "Validar carga, operación y costos antes del diseño final.",
                    "status": "inferred",
                    "citations": [],
                }
            ],
            "open_questions": project["questions"],
            "related_projects": [
                {
                    "project_id": project["reference_id"],
                    "reason": "Antecedente académico ficticio para comparar patrones, no resultados comprobados.",
                    "citations": [
                        {
                            "source_id": document["path"],
                            "quote": project["reference_quote"],
                        }
                    ],
                }
            ],
            "presentation": [
                {"title": f"Idea {n}", "bullets": [idea]}
                for n, idea in enumerate(project["ideas"], 1)
            ],
            "speaker_notes": "",
        }
        payload = json.loads(json.dumps(payload))
        if state.get("feedback"):
            # This is a scripted provider, not a claim of natural-language understanding.
            payload["open_questions"].append(
                f"Ajuste solicitado por Stuart: {state['feedback']}"
            )
        self.store.event(
            f"mock-draft:{state['case_id']}:{state.get('revision', 0) + 1}",
            state["case_id"],
            "mock.preparation.completed",
            {
                "provider": "scripted_mock",
                "searched": project["search_query"],
                "read_reference": project["reference_id"],
                "is_simulated": True,
            },
        )
        self.clock.advance(5)
        return ExecutivePackage.model_validate(payload).validate_sources(
            sources, {project["reference_id"]}
        )
