"""Block Kit poll and signed Slack actions; no operator-supplied vote endpoint."""

import hashlib
import hmac
import json
import time
import uuid
from urllib.parse import parse_qs

from app.integrations.errors import ProviderError
from app.integrations.slack import SlackNotifier


def slack_text(text):
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def poll_blocks(ballot):
    text = f"*Votación de junta*\n{slack_text(ballot['title'])}\nPresupuesto: {ballot['budget']['currency']} {ballot['budget']['total']}\nRegla: unanimidad ({len(ballot['members'])} miembros)."
    labels = {
        "approve": "A favor",
        "reject": "En contra",
        "abstain": "Abstención",
        "pending": "Pendiente",
    }
    members = "\n".join(
        f"• {slack_text(m['name'])}: "
        + labels[ballot["votes"].get(m["slack_id"], {}).get("choice", "pending")]
        for m in ballot["members"]
    )
    inputs = "\n".join(
        f"• {slack_text(f['name'])}: `{f['sha256']}`" for f in ballot["files"]
    )
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": text}},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Miembros y votos*\n" + members},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Insumos sometidos a votación*\n" + inputs,
            },
        },
    ]
    budget = "\n".join(
        f"• {slack_text(line['name'])}: {ballot['budget']['currency']} {line['amount']}"
        for line in ballot["budget"]["lines"]
    )
    blocks.insert(
        1,
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Partidas del presupuesto*\n"
                + budget
                + f"\nVersión: `{ballot['request_sha256']}`",
            },
        },
    )
    if ballot["review_url"]:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"<{ballot['review_url']}|Revisar el paquete de insumos>",
                },
            }
        )
    if ballot["status"] in {"planned", "publishing", "open"}:
        blocks.append(
            {
                "type": "actions",
                "block_id": "board:" + ballot["id"],
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": label},
                        "action_id": "board_" + choice,
                        "value": ballot["id"],
                    }
                    for choice, label in [
                        ("approve", "Aprobar"),
                        ("reject", "Rechazar"),
                        ("abstain", "Abstenerse"),
                    ]
                ],
            }
        )
    else:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "plain_text",
                    "text": "Aprobado por unanimidad"
                    if ballot["status"] == "approved"
                    else "No aprobado",
                },
            }
        )
    return blocks


class SlackBoardPoll(SlackNotifier):
    def __init__(self, token, client=None):
        super().__init__(token, "", client)

    def validate(self, ballot):
        if not self.token:
            raise ValueError("Configurar SLACK_BOT_TOKEN para publicar la votación.")
        identity = self._post("auth.test", {})
        if identity["team_id"] != ballot["team_id"]:
            raise ValueError("La cuenta Slack corresponde a otro workspace.")
        for member in ballot["members"]:
            user = self._post("users.info", {"user": member["slack_id"]})["user"]
            if (
                user.get("deleted")
                or user.get("is_bot")
                or user["id"] != member["slack_id"]
            ):
                raise ValueError("La junta contiene una identidad Slack no habilitada.")

    def send(self, ballot):
        sent = self._post(
            "chat.postMessage",
            {
                "channel": ballot["channel_id"],
                "text": "Votación de junta: " + ballot["title"],
                "blocks": poll_blocks(ballot),
                "client_msg_id": str(uuid.UUID(ballot["id"])),
                "unfurl_links": False,
                "unfurl_media": False,
            },
            sending=True,
        )
        if not sent.get("ts") or sent.get("channel") != ballot["channel_id"]:
            raise ProviderError("slack_board_receipt_missing", ambiguous=True)
        return {"channel": sent["channel"], "ts": sent["ts"]}

    def reconcile(self, ballot, message_ts):
        messages = self._post(
            "conversations.history",
            {
                "channel": ballot["channel_id"],
                "oldest": message_ts,
                "latest": message_ts,
                "inclusive": True,
                "limit": 1,
            },
        )["messages"]
        expected = "board:" + ballot["id"]
        if (
            len(messages) != 1
            or messages[0]["ts"] != message_ts
            or not any(
                b.get("block_id") == expected for b in messages[0].get("blocks", [])
            )
        ):
            raise ValueError("El mensaje Slack no corresponde a esta convocatoria.")
        return {"channel": ballot["channel_id"], "ts": message_ts}

    def update(self, ballot):
        self._post(
            "chat.update",
            {
                "channel": ballot["channel_id"],
                "ts": ballot["receipt"]["ts"],
                "text": "Votación de junta: " + ballot["title"],
                "blocks": poll_blocks(ballot),
            },
        )


class SlackBoardActions:
    def __init__(self, service, signing_secret, clock=time.time):
        self.service, self.signing_secret, self.clock = service, signing_secret, clock

    def handle(self, raw, timestamp, signature):
        now = self.clock()
        verify_slack_signature(raw, timestamp, signature, self.signing_secret, now)
        payload = json.loads(parse_qs(raw.decode(), strict_parsing=True)["payload"][0])
        if (
            payload.get("type") != "block_actions"
            or len(payload.get("actions", [])) != 1
        ):
            raise ValueError("Interacción Slack inválida.")
        action = payload["actions"][0]
        if action["action_id"] not in {
            "board_approve",
            "board_reject",
            "board_abstain",
        }:
            raise ValueError("Acción de junta inválida.")
        action_ts = action["action_ts"]
        if abs(now - float(action_ts)) > 300:
            raise ValueError("El voto Slack está fuera de la ventana de recepción.")
        return self.service.record_action(
            {
                "ballot_id": action["value"],
                "choice": action["action_id"].removeprefix("board_"),
                "user_id": payload["user"]["id"],
                "team_id": payload["team"]["id"],
                "app_id": payload["api_app_id"],
                "channel_id": payload["channel"]["id"],
                "message_ts": payload["container"]["message_ts"],
                "action_ts": action_ts,
                "received_at": now,
                "body_sha256": hashlib.sha256(raw).hexdigest(),
            }
        )


def verify_slack_signature(raw, timestamp, signature, secret, now):
    if not secret:
        raise ValueError("La recepción de votos Slack no está configurada.")
    if len(raw) > 100_000 or abs(now - int(timestamp)) > 300:
        raise ValueError("Solicitud Slack vencida o demasiado grande.")
    expected = (
        "v0="
        + hmac.new(
            secret.encode(), b"v0:" + timestamp.encode() + b":" + raw, hashlib.sha256
        ).hexdigest()
    )
    if not hmac.compare_digest(expected, signature):
        raise ValueError("Firma Slack inválida.")
