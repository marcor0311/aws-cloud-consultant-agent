"""Project queue and decision records in the existing workflow database."""

from app.preparation.deliveries import files_digest
from app.project_opening.models import project_identity, slug


class ProjectOpeningRepository:
    def __init__(self, store):
        self.store = store

    def get(self, case_id):
        record = self.store.get(f"opening:{case_id}")
        if record is None:
            raise ValueError("Proyecto no registrado en la cola.")
        queue = self.store.get("opening-registry:queue") or {"cases": []}
        if case_id in queue["cases"]:
            record = {**record, "queue_position": queue["cases"].index(case_id) + 1}
        return record

    def lock(self, key):
        return self.store.lock(f"opening:{key}")

    def work(self, case_id):
        return self.store.work(case_id, "project-opening", "meeting-assistant")

    def preparation_delivery(self, case_id, files):
        status = self.store.get(f"status:{case_id}")
        if not status or status["status"] != "ready_for_stage_2":
            raise ValueError("Falta la entrega aprobada y persistida del agente 1.")
        revision = status["revision"]
        manifest = self.store.get(f"artifact-files:{case_id}:{revision}")
        handoff = self.store.handoff(f"{case_id}:stage-1:stage-2:v{revision}")
        if (
            not manifest
            or not handoff
            or manifest["files_sha256"] != files_digest(files)
            or manifest["artifact_sha256"] != handoff["artifact_sha256"]
            or handoff["to_actor"]
            not in {"meeting-assistant", "executive-direction-agent"}
        ):
            raise ValueError(
                "Los insumos no corresponden a la entrega aprobada del agente 1."
            )
        return {
            "handoff_id": handoff["id"],
            "revision": revision,
            "artifact_sha256": manifest["artifact_sha256"],
            "files_sha256": manifest["files_sha256"],
        }

    def accept_preparation(self, record, source):
        incoming = self.store.handoff(source["handoff_id"])
        receipt = self.store.accept_handoff(
            incoming["id"],
            "meeting-assistant",
            acting_for=incoming["to_actor"]
            if incoming["to_actor"] != "meeting-assistant"
            else None,
        )
        result = self.update(
            record["case_id"],
            incoming_preparation={
                **source,
                "accepted_at": receipt["accepted_at"],
                "accepted_by": receipt["accepted_by"],
            },
        )
        self.store.event(
            "opening-source:" + record["case_id"],
            record["case_id"],
            "opening.preparation_received",
            {**source, "consumer_agent": "meeting-assistant"},
        )
        return result

    def validate_preparation(self, record):
        expected = self.preparation_delivery(record["case_id"], record["files"])
        received = record.get("incoming_preparation") or {}
        if (
            received.get("handoff_id") != expected["handoff_id"]
            or received.get("files_sha256") != expected["files_sha256"]
            or not self.store.handoff(expected["handoff_id"])["accepted_at"]
        ):
            raise ValueError("El agente 2 todavía no recibió la entrega del agente 1.")

    def reserve(self, request):
        with self.lock("registry"):
            previous = self.store.get(f"opening:{request.case_id}")
            if previous:
                if previous["request_sha256"] != request.fingerprint():
                    raise ValueError("El expediente ya tiene otra decisión aprobada.")
                return previous
            queue = self.store.get("opening-registry:queue") or {"cases": []}
            counter_key = f"opening-number:{slug(request.company)}"
            counter = self.store.get(counter_key) or {"last": 0}
            number = counter["last"] + 1
            identity = project_identity(request.company, number, request.project_name)
            if request.queue_position > len(queue["cases"]) + 1:
                raise ValueError("La posición debe estar dentro de la cola actual.")
            cases = list(queue["cases"])
            cases.insert(request.queue_position - 1, request.case_id)
            record = {
                **request.model_dump(mode="json"),
                **identity,
                "project_number": number,
                "request_sha256": request.fingerprint(),
                "approved_at": self.store.clock(),
                "requested_queue_position": request.queue_position,
                "status": "queued",
                "repository": None,
                "commit": None,
                "issue": None,
            }
            with self.store.engine.begin() as db:
                self.store.put_in(db, counter_key, "opening-number", {"last": number})
                self.store.put_in(
                    db, "opening-registry:queue", "opening-queue", {"cases": cases}
                )
                self.store.put_in(db, f"opening:{request.case_id}", "opening", record)
            self.store.phase(request.case_id, "project-opening", request.approved_by)
            self.store.event(
                f"opening-approved:{request.case_id}",
                request.case_id,
                "opening.approved",
                {"request_sha256": request.fingerprint(), "actor": request.approved_by},
            )
            return record

    def accept_board(self, case_id, certificate):
        handoff_id = "board:" + certificate["id"] + ":decision"
        handoff = self.store.handoff(handoff_id)
        if not handoff or handoff["artifact_sha256"] != certificate["digest"]:
            raise ValueError("Falta la entrega persistida del acta de junta.")
        self.store.accept_handoff(handoff_id, "meeting-assistant")

    def queue(self):
        queue = self.store.get("opening-registry:queue") or {"cases": []}
        return [
            {**self.get(case), "queue_position": i}
            for i, case in enumerate(queue["cases"], 1)
        ]

    def audit(self, case_id):
        record = self.get(case_id)
        status = self.store.get(f"status:{case_id}")
        manifest = (
            self.store.get(f"artifact-files:{case_id}:{status['revision']}")
            if status
            else None
        )
        source = self.store.get(f"local-transcript:{case_id}")
        current_board = self.store.get("board-current:" + case_id)
        ballot = (
            self.store.get("board-ballot:" + current_board["id"])
            if current_board
            else None
        )
        return {
            "case_id": case_id,
            "database": self.store.engine.dialect.name,
            "opening_status": record["status"],
            "queue_position": record["queue_position"],
            "architect": record["architect"],
            "preparation": status,
            "source": {
                k: source[k]
                for k in (
                    "source_id",
                    "provenance",
                    "recorded_at",
                    "historical_occurred_at",
                )
            }
            if source
            else None,
            "files_manifest": manifest,
            "incoming_preparation": record.get("incoming_preparation"),
            "board": {
                "status": ballot["status"],
                "votes": len(ballot["votes"]),
                "members": len(ballot["members"]),
                "is_simulated": ballot["is_simulated"],
            }
            if ballot
            else None,
            "handoffs": self.store.case_handoffs(case_id),
            "events": self.store.case_events(case_id),
        }

    def update(self, case_id, **changes):
        record = {**self.get(case_id), **changes}
        self.store.put(f"opening:{case_id}", "opening", record)
        if "status" in changes:
            self.store.event(
                f"opening-step:{case_id}:{changes['status']}",
                case_id,
                "opening.progress",
                {"status": changes["status"]},
            )
        return record

    def deliver(self, record):
        certificate = record["board_approval"]
        self.store.create_handoff(
            f"opening:{record['case_id']}:architecture:board:{certificate['digest']}",
            record["case_id"],
            "meeting-assistant",
            record["architect"],
            "project-opening",
            "architecture",
            revision=1,
            artifact_sha256=certificate["digest"],
        )
        self.store.complete_phase(record["case_id"], "project-opening")
