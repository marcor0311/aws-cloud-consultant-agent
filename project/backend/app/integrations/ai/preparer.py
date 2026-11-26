"""API-key preparation from this meeting's sources; no project catalog or tools."""

import json

import httpx

from app.integrations.errors import ConfigurationError, ProviderError
from app.preparation.models import MEETING_EVIDENCE_INSTRUCTIONS, ExecutivePackage
from app.preparation.processing import PROCESSOR_INSTRUCTIONS, ProcessedMeeting
from app.preparation.state import meeting_sources


class OpenAIPreparer:
    def __init__(
        self,
        key,
        model,
        client=None,
        *,
        allow_inference=False,
        package_model=ProcessedMeeting,
    ):
        self.package_model = package_model
        self.key, self.model = key, model
        self.client = client or httpx.Client(timeout=60)
        self.allow_inference = allow_inference

    def __call__(self, state):
        if not self.allow_inference:
            raise ConfigurationError("real_inference_requires_explicit_activation")
        if not self.key or not self.model:
            raise ConfigurationError("configure_openai_key_and_workflow_model")
        try:
            response = self.client.post(
                "https://api.openai.com/v1/responses",
                headers={"Authorization": f"Bearer {self.key}"},
                json={
                    "model": self.model,
                    "max_output_tokens": 6000,
                    "store": False,
                    "instructions": PROCESSOR_INSTRUCTIONS
                    if self.package_model is ProcessedMeeting
                    else MEETING_EVIDENCE_INSTRUCTIONS,
                    "input": [
                        {
                            "role": "user",
                            "content": json.dumps(
                                {
                                    "transcript": state["transcript"],
                                    "meeting_notes": state.get("meeting_notes", ""),
                                    "feedback": state.get("feedback", ""),
                                },
                                ensure_ascii=False,
                            ),
                        }
                    ],
                    "text": {
                        "format": {
                            "type": "json_schema",
                            "name": "executive_package",
                            "strict": True,
                            "schema": self.package_model.model_json_schema(),
                        }
                    },
                },
            )
        except httpx.HTTPError:
            raise ProviderError("model_transport_error") from None
        if response.status_code != 200:
            raise ProviderError(f"model_http_{response.status_code}")
        payload = response.json()
        if payload.get("status") != "completed":
            raise ProviderError("model_response_incomplete")
        text = "".join(
            part.get("text", "")
            for item in payload.get("output", [])
            if item.get("type") == "message"
            for part in item.get("content", [])
            if part.get("type") == "output_text"
        )
        try:
            package = self.package_model.model_validate_json(text)
            return (
                package.validate_sources(meeting_sources(state))
                if isinstance(package, ExecutivePackage)
                else package
            )
        except ValueError:
            raise ProviderError("model_output_or_citations_invalid") from None
