"""Board rosters, signed-vote receipts and immutable decision snapshots in workflow SQL."""

import time
import uuid
from contextlib import ExitStack, contextmanager

from app.persistence.locking import Busy
from app.project_opening.board import digest


class BoardRepository:
    def __init__(self, store):
        self.store = store

    @contextmanager
    def lock(self, ballot_id):
        # Serialize simultaneous clicks while staying inside Slack's ACK window.
        deadline = time.monotonic() + 1.5
        with ExitStack() as stack:
            while True:
                try:
                    stack.enter_context(self.store.lock("board-ballot:" + ballot_id))
                    break
                except Busy:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.01)
            yield

    def get(self, ballot_id):
        ballot = self.store.get("board-ballot:" + ballot_id)
        if ballot is None:
            raise ValueError("Votación no registrada.")
        return ballot

    def latest(self, case_id):
        current = self.store.get("board-current:" + case_id)
        return self.get(current["id"]) if current else None

    def prepare(self, record, config, *, new_round=False):
        previous = self.latest(record["case_id"])
        identity = digest(
            {"request_sha256": record["request_sha256"], "config": config}
        )
        if previous and previous["identity"] == identity and not new_round:
            return previous
        ballot = {
            "id": uuid.uuid4().hex,
            "identity": identity,
            **{
                k: record[k]
                for k in ["case_id", "title", "request_sha256", "files", "budget"]
            },
            **config,
            "rule": "unanimity",
            "opened_at": self.store.clock(),
            "closed_at": None,
            "votes": {},
            "status": "planned",
            "receipt": {},
            "certificate": None,
        }
        with self.store.engine.begin() as db:
            self.store.put_in(
                db, "board-ballot:" + ballot["id"], "board-ballot", ballot
            )
            self.store.put_in(
                db,
                "board-current:" + record["case_id"],
                "board-current",
                {"id": ballot["id"]},
            )
        return ballot

    def save(self, ballot):
        previous = self.get(ballot["id"])
        if previous.get("certificate") and ballot != previous:
            raise ValueError(
                "Un acta cerrada no se modifica; requiere nueva convocatoria."
            )
        self.store.put("board-ballot:" + ballot["id"], "board-ballot", ballot)
        self._sync_handoffs(ballot)
        if ballot.get("certificate"):
            self.store.event(
                "board-sealed:" + ballot["id"],
                ballot["case_id"],
                "board.decision_sealed",
                {"status": ballot["status"], "digest": ballot["certificate"]["digest"]},
            )
        return ballot

    def _sync_handoffs(self, ballot):
        if not ballot["receipt"].get("ts"):
            return
        for member in ballot["members"]:
            actor = "slack:" + member["slack_id"]
            handoff_id = f"board:{ballot['id']}:member:{member['slack_id']}"
            self.store.create_handoff(
                handoff_id,
                ballot["case_id"],
                "meeting-assistant",
                actor,
                "board-convocation",
                "board-review",
                revision=1,
                artifact_sha256=ballot["identity"],
            )
            if member["slack_id"] in ballot["votes"]:
                self.store.accept_handoff(handoff_id, actor)
        if ballot.get("certificate"):
            self.store.create_handoff(
                "board:" + ballot["id"] + ":decision",
                ballot["case_id"],
                "board",
                "meeting-assistant",
                "board-review",
                "project-opening",
                revision=1,
                artifact_sha256=ballot["certificate"]["digest"],
            )
