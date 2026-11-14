"""Unanimous board decisions; identities come from verified Slack interactions."""

import hashlib
import json
from datetime import datetime, timezone

from pydantic import Field, model_validator

from app.project_opening.models import Input


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def iso_time(timestamp):
    return datetime.fromtimestamp(float(timestamp), timezone.utc).isoformat()


class BoardMember(Input):
    slack_id: str = Field(pattern=r"^[UW][A-Z0-9]+$")
    name: str = Field(min_length=1, max_length=120)


class BoardConfig(Input):
    team_id: str = Field(pattern=r"^T[A-Z0-9]+$")
    app_id: str = Field(pattern=r"^A[A-Z0-9]+$")
    channel_id: str = Field(pattern=r"^[CG][A-Z0-9]+$")
    members: list[BoardMember] = Field(min_length=4, max_length=5)
    review_url: str = Field(default="", pattern=r"^(https://[^\s]+)?$")
    is_simulated: bool = False

    @model_validator(mode="after")
    def distinct(self):
        if len({m.slack_id for m in self.members}) != len(self.members):
            raise ValueError("Cada miembro debe tener una identidad Slack distinta.")
        return self


def result_for(ballot):
    votes = ballot["votes"]
    if len(votes) != len(ballot["members"]):
        return "open"
    return (
        "approved"
        if all(v["choice"] == "approve" for v in votes.values())
        else "not_approved"
    )


def certificate_for(ballot):
    if ballot["status"] not in {"approved", "not_approved"}:
        raise ValueError("La votación todavía no está completa.")
    if (
        set(ballot["votes"]) != {m["slack_id"] for m in ballot["members"]}
        or not all(
            v.get("signature_verified") is True for v in ballot["votes"].values()
        )
        or result_for(ballot) != ballot["status"]
    ):
        raise ValueError("Los votos no respaldan el resultado de la junta.")
    certificate = {
        key: ballot[key]
        for key in [
            "id",
            "case_id",
            "title",
            "request_sha256",
            "budget",
            "files",
            "members",
            "votes",
            "rule",
            "opened_at",
            "closed_at",
            "status",
            "is_simulated",
            "team_id",
            "app_id",
            "channel_id",
            "receipt",
            "review_url",
        ]
    }
    certificate["digest"] = digest(certificate)
    return certificate


class BoardService:
    def __init__(
        self, repository, opening_repository, slack, clock, render_documents=None
    ):
        self.repository = repository
        self.openings = opening_repository
        self.slack = slack
        self.clock = clock
        self.render_documents = render_documents

    def prepare(self, case_id, config, new_round=False):
        config = BoardConfig.model_validate(config)
        with self.openings.lock(case_id):
            record = self.openings.get(case_id)
            return self.repository.prepare(
                record, config.model_dump(mode="json"), new_round=new_round
            )

    def get(self, ballot_id):
        return self.repository.get(ballot_id)

    def minutes(self, ballot_id):
        ballot = self.get(ballot_id)
        if not ballot.get("certificate") or self.render_documents is None:
            raise ValueError("El acta requiere una votación cerrada y documentada.")
        return {
            name: data.decode()
            for name, data in self.render_documents(ballot["certificate"]).items()
        }

    def publish(self, ballot_id):
        with self.repository.lock(ballot_id):
            ballot = self.get(ballot_id)
            if ballot["status"] in {"open", "approved", "not_approved"}:
                return ballot
            if ballot["status"] in {"publishing", "send_uncertain"}:
                raise ValueError(
                    "El envío Slack requiere conciliación; no se repite automáticamente."
                )
            if ballot["is_simulated"]:
                raise ValueError("Una votación simulada no se publica en Slack real.")
            if not ballot["review_url"]:
                raise ValueError(
                    "Configurar el enlace de revisión del paquete aprobado, incluido el guion."
                )
            self.slack.validate(ballot)
            self.repository.save({**ballot, "status": "publishing"})
            try:
                receipt = self.slack.send(ballot)
            except Exception as error:
                status = (
                    "send_uncertain" if getattr(error, "ambiguous", True) else "planned"
                )
                self.repository.save({**ballot, "status": status})
                raise
            return self.repository.save(
                {
                    **ballot,
                    "status": "open",
                    "receipt": receipt,
                    "opened_at": float(receipt["ts"]),
                }
            )

    def reconcile(self, ballot_id, message_ts):
        with self.repository.lock(ballot_id):
            ballot = self.get(ballot_id)
            if ballot["status"] not in {"publishing", "send_uncertain"}:
                raise ValueError("Solo se concilian envíos pendientes de confirmación.")
            receipt = self.slack.reconcile(ballot, message_ts)
            return self.repository.save(
                {
                    **ballot,
                    "status": "open",
                    "receipt": receipt,
                    "opened_at": float(receipt["ts"]),
                }
            )

    def record_action(self, action):
        """Called by the signature-verifying adapter; deliberately not exposed through MCP."""
        with self.repository.lock(action["ballot_id"]):
            ballot = self.get(action["ballot_id"])
            if not ballot["receipt"].get("ts"):
                raise ValueError("La votación todavía no se ha publicado.")
            if (
                action["team_id"],
                action["app_id"],
                action["channel_id"],
                action["message_ts"],
            ) != (
                ballot["team_id"],
                ballot["app_id"],
                ballot["channel_id"],
                ballot["receipt"]["ts"],
            ):
                raise ValueError("El voto no corresponde a esta votación y mensaje.")
            if not isinstance(action["user_id"], str) or action["user_id"] not in {
                m["slack_id"] for m in ballot["members"]
            }:
                raise ValueError("La persona no pertenece a la junta registrada.")
            if action["choice"] not in {"approve", "reject", "abstain"}:
                raise ValueError("Opción de voto inválida.")
            if (
                action["received_at"] < ballot["opened_at"]
                or float(action["action_ts"]) < ballot["opened_at"]
            ):
                raise ValueError("El voto es anterior a la convocatoria.")
            existing = ballot["votes"].get(action["user_id"])
            if existing:
                if existing["choice"] != action["choice"]:
                    raise ValueError(
                        "El voto ya fue registrado; una reconsideración requiere nueva convocatoria."
                    )
                return ballot
            if ballot["status"] != "open":
                raise ValueError("La votación no está abierta.")
            vote = {
                "choice": action["choice"],
                "action_ts": action["action_ts"],
                "voted_at": iso_time(action["action_ts"]),
                "received_at": iso_time(action["received_at"]),
                "request_body_sha256": action["body_sha256"],
                "signature_verified": True,
            }
            updated = {**ballot, "votes": {**ballot["votes"], action["user_id"]: vote}}
            updated["status"] = result_for(updated)
            if updated["status"] != "open":
                updated["closed_at"] = iso_time(
                    max(
                        self.clock(),
                        *(float(v["action_ts"]) for v in updated["votes"].values()),
                    )
                )
                updated["certificate"] = certificate_for(updated)
                if self.render_documents is not None:
                    updated["documents"] = {
                        name: data.decode()
                        for name, data in self.render_documents(
                            updated["certificate"]
                        ).items()
                    }
            return self.repository.save(updated)

    def require_approval(self, case_id, *, allow_simulated=False):
        ballot = self.repository.latest(case_id)
        record = self.openings.get(case_id)
        if not ballot or ballot["status"] != "approved":
            raise ValueError("La junta todavía no ha aprobado por unanimidad.")
        if (
            ballot["request_sha256"] != record["request_sha256"]
            or ballot["files"] != record["files"]
            or ballot["budget"] != record["budget"]
            or ballot["title"] != record["title"]
        ):
            raise ValueError("La aprobación corresponde a otra versión de los insumos.")
        if ballot["is_simulated"] and not allow_simulated:
            raise ValueError("Los votos simulados no autorizan una apertura real.")
        if certificate_for(ballot) != ballot.get("certificate"):
            raise ValueError("El acta no coincide con los votos registrados.")
        return ballot["certificate"]

    def sync_poll(self, ballot_id):
        ballot = self.get(ballot_id)
        if not ballot["is_simulated"]:
            self.slack.update(ballot)
