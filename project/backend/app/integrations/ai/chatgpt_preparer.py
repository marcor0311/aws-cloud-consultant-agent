"""Subscription-backed preparation, run only by the durable local worker."""

import hashlib
import json

import httpx
from openai import APIError, OpenAI

from app.integrations.ai.oauth import RESOURCE, DemoError, checked
from app.integrations.errors import ConfigurationError
from app.preparation.processing import PROCESSOR_INSTRUCTIONS, ProcessedMeeting


def generation_key(state):
    identity = [
        state["case_id"],
        state["input_hash"],
        state.get("revision", 0) + 1,
        state.get("feedback", ""),
    ]
    return (
        "preparation-inference:"
        + hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    )


class ChatGPTPreparer:
    def __init__(self, session, model, store, *, allow_inference=False):
        self.session, self.model, self.store = session, model, store
        self.allow_inference = allow_inference

    def __call__(self, state):
        if not self.allow_inference:
            raise ConfigurationError("real_inference_requires_explicit_activation")
        if not self.model:
            raise ConfigurationError("configure_workflow_model")
        key = generation_key(state)
        try:
            if callable(self.session):
                self.session = self.session()
            headers = self.session.headers()
            catalog = checked(
                self.session.client.get(RESOURCE + "/models", headers=headers),
                "Catálogo del plan",
            ).json()
            models = catalog.get("models", catalog.get("data", []))
            if self.model not in {
                row.get("slug", row.get("id"))
                for row in models
                if row.get("visibility", "list") == "list"
            }:
                raise ConfigurationError("chatgpt_model_unavailable")
        except (DemoError, httpx.HTTPError, ValueError, KeyError):
            raise ConfigurationError("chatgpt_session_requires_attention") from None

        client = OpenAI(
            api_key=self.session.access_token,
            base_url=RESOURCE,
            http_client=self.session.client,
            max_retries=0,
        )
        parts, completed = {}, None
        try:
            with client.responses.create(
                model=self.model,
                store=False,
                stream=True,
                instructions=PROCESSOR_INSTRUCTIONS,
                input=[
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "transcript": state["transcript"],
                                "feedback": state.get("feedback", ""),
                            },
                            ensure_ascii=False,
                        ),
                    }
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "executive_package",
                        "strict": True,
                        "schema": ProcessedMeeting.model_json_schema(),
                    }
                },
            ) as stream:
                for event in stream:
                    index = (
                        getattr(event, "output_index", 0),
                        getattr(event, "content_index", 0),
                    )
                    if event.type == "response.output_text.delta":
                        parts[index] = parts.get(index, "") + event.delta
                    elif event.type == "response.output_text.done":
                        parts[index] = event.text
                    elif (
                        event.type == "response.completed"
                        and event.response.status == "completed"
                    ):
                        completed = event.response
                    elif event.type in {
                        "response.failed",
                        "response.incomplete",
                        "error",
                    }:
                        raise ConfigurationError("chatgpt_preparation_incomplete")
        except (APIError, httpx.HTTPError):
            raise ConfigurationError("chatgpt_preparation_unavailable") from None
        if completed is None:
            raise ConfigurationError("chatgpt_preparation_incomplete")
        try:
            package = ProcessedMeeting.model_validate_json(
                "".join(parts[i] for i in sorted(parts))
            )
        except ValueError:
            raise ConfigurationError("model_output_or_citations_invalid") from None
        self.store.put(
            key,
            "preparation_inference",
            {
                "case_id": state["case_id"],
                "status": "completed",
                "response_id": completed.id,
                "model": self.model,
                "usage": completed.usage.model_dump() if completed.usage else None,
                "authentication": "chatgpt_plan_oauth",
                "api_key_fallback": False,
            },
        )
        return package
