"""External adapters. No credentials or transcript bodies in error messages."""

import re

import httpx

from app.integrations.errors import ConfigurationError, ProviderError


class SlackNotifier:
    def __init__(self, token, user_id, client=None):
        self.token, self.user_id = token, user_id
        self.client = client or httpx.Client(timeout=20)

    def _post(self, method, body, *, sending=False):
        try:
            response = self.client.post(
                f"https://slack.com/api/{method}",
                json=body,
                headers={"Authorization": f"Bearer {self.token}"},
            )
        except (httpx.TimeoutException, httpx.NetworkError):
            raise ProviderError("slack_transport_error", ambiguous=sending) from None
        if response.status_code == 429:
            raise ProviderError(
                "slack_rate_limited",
                retry_after=max(1, int(response.headers.get("Retry-After", "30"))),
            )
        if response.status_code >= 500:
            raise ProviderError("slack_server_error", ambiguous=sending)
        try:
            payload = response.json()
        except ValueError:
            raise ProviderError("slack_invalid_response", ambiguous=sending) from None
        if response.status_code != 200 or not payload.get("ok"):
            # Slack explicitly rejected the operation; no message receipt exists.
            raise ConfigurationError("slack_request_rejected")
        return payload

    def send(self, notice, notification_id):
        if not self.token or not re.fullmatch(r"[UW][A-Z0-9]+", self.user_id):
            raise ConfigurationError("configure_slack_bot_and_em_user")
        channel = self._post("conversations.open", {"users": self.user_id})["channel"][
            "id"
        ]
        status = {
            "awaiting_review": "Borrador listo para revisión",
            "ready_for_stage_2": "Paquete aprobado para dirección ejecutiva",
            "needs_attention": "El expediente requiere intervención",
        }.get(notice["status"], notice["status"])
        text = (
            f"{status}. Expediente {notice['case_id']} · versión {notice['revision']}. "
            "Abre ChatGPT y consulta el expediente mediante el MCP de preparación."
        )
        result = self._post(
            "chat.postMessage",
            {
                "channel": channel,
                "text": text,
                "unfurl_links": False,
                "unfurl_media": False,
                "client_msg_id": notification_id,
            },
            sending=True,
        )
        if not result.get("ts") or not result.get("channel"):
            raise ProviderError("slack_receipt_missing", ambiguous=True)
        return {"channel": result["channel"], "ts": result["ts"]}
