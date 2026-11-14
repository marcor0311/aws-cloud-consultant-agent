"""Deliver a sealed negative board result to the six-stage process, offline."""

from app.project_opening.board import certificate_for


class BoardDecisionBlocked(ValueError):
    """The durable vote is valid, but its process correspondence needs reconciliation."""


class BoardRejectionDelivery:
    def __init__(self, boards, openings, process):
        self.boards, self.openings, self.process = boards, openings, process

    def deliver(self, payload):
        try:
            return self._deliver(payload)
        except (ValueError, KeyError, TypeError) as error:
            raise BoardDecisionBlocked(
                f"No se pudo vincular el rechazo de junta: {error}"
            ) from error

    def _deliver(self, payload):
        case_id = payload["case_id"]
        ballot = self.boards.get(payload["ballot_id"])
        certificate = certificate_for(ballot)
        record = self.openings.get(case_id)
        if (
            ballot["case_id"] != case_id
            or ballot["status"] != "not_approved"
            or certificate != ballot.get("certificate")
            or certificate["digest"] != payload["certificate_sha256"]
            or any(
                certificate[key] != record[key]
                for key in ("case_id", "request_sha256", "files", "budget", "title")
            )
        ):
            raise ValueError("El certificado no corresponde a la apertura persistida.")
        self.openings.validate_preparation(record)
        source = record["incoming_preparation"]
        state = self.process.get(case_id)["state"]
        approvals = [
            event
            for event in state["history"]
            if event["kind"] == "preparation.approved"
            and event.get("revision") == source["revision"]
            and event.get("artifact_sha256") == source["artifact_sha256"]
            and event["to_stage"] == 2
        ]
        if len(approvals) != 1:
            raise ValueError("Falta la aprobación exacta de preparación en el proceso.")

        # Recover projections if sealing committed before the board handoff did.
        self.boards.save(ballot)
        handoff = self.boards.store.handoff(f"board:{ballot['id']}:decision")
        if (
            not handoff
            or handoff["case_id"] != case_id
            or handoff["artifact_sha256"] != certificate["digest"]
        ):
            raise ValueError("Falta la entrega del certificado de esta votación.")
        stem = f"docs/02-board/acta-junta-{ballot['id']}"
        event = {
            "event_id": f"board-rejected:{ballot['id']}:{certificate['digest']}",
            "kind": "stage.rejected",
            "stage": approvals[0]["to_stage"],
            "iteration": approvals[0]["to_iteration"],
            "revision": source["revision"],
            "artifact_sha256": source["artifact_sha256"],
            "actor": handoff["from_actor"],
            "origin": "internal",
            # The certified result is the reason; no human comment is inferred.
            "comment": certificate["status"],
            "evidence": [
                f"board-ballot:{ballot['id']}",
                handoff["id"],
                f"sha256:{certificate['digest']}",
                stem + ".md",
                stem + ".json",
            ],
        }
        result = self.process.apply(case_id, event)
        self.openings.accept_board(case_id, certificate)
        self.openings.update(
            case_id,
            status="declined",
            board_decision={"id": ballot["id"], "digest": certificate["digest"]},
        )
        self.boards.store.complete_phase(case_id, "stage-2")
        self.boards.store.complete_phase(case_id, "project-opening")
        return {"status": result["state"]["status"], "event_id": event["event_id"]}
