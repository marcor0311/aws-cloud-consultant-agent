"""OAuth security and subscription-only LangGraph proof, without real credentials."""

import json
import re
import time
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.demos.chatgpt import (
    DemoError,
    PlanConnection,
    create_app,
    run_graph,
)
from app.integrations.ai.oauth import ISSUER, RESOURCE


@pytest.fixture
def provider(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "must-never-be-used")
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    key["kid"] = "demo-test-key"
    scenario = {"scope": "resource.invoke chatgpt.tokens.use.direct", "complete": True}
    requests = []
    connection = None

    def respond(request):
        requests.append(request)
        if request.url.path.endswith("/token"):
            fields = parse_qs(request.content.decode())
            assert fields["client_id"] == ["oaiapp_test"]
            assert fields["redirect_uri"] == [connection.redirect_uri]
            assert fields["resource"] == [RESOURCE]
            assert "client_secret" not in fields
            claims = {
                "sub": "demo-subject",
                "iss": ISSUER,
                "aud": "oaiapp_test",
                "exp": int(time.time()) + 300,
                "iat": int(time.time()),
                "nonce": scenario["nonce"],
            }
            claims.update(scenario.get("claims", {}))
            return httpx.Response(
                200,
                json={
                    "id_token": jwt.encode(
                        claims,
                        private_key,
                        algorithm="RS256",
                        headers={"kid": key["kid"]},
                    ),
                    "access_token": "oauth-test-access",
                    "expires_in": 3600,
                    "scope": scenario["scope"],
                },
            )
        if request.url.path.endswith("/jwks.json"):
            return httpx.Response(200, json={"keys": [key]})
        assert request.headers["Authorization"] == "Bearer oauth-test-access"
        if request.url.path == "/v1/models":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "slug": "test-model",
                            "display_name": "Test model",
                            "visibility": "list",
                        },
                    ]
                },
            )
        assert request.url.path == "/v1/responses"
        payload = json.loads(request.content)
        assert payload["store"] is False and payload["stream"] is True
        assert payload["model"] == "test-model"
        assert "TRANSCRIPCIÓN FICTICIA" in payload["input"][0]["content"]
        if "wire" in scenario:
            return httpx.Response(
                200,
                text=scenario["wire"],
                headers={"content-type": "text/event-stream"},
            )
        if scenario.get("rate_limit"):
            return httpx.Response(
                429,
                json={
                    "error": {
                        "code": "subscription_sharing_usage_limit_exceeded",
                        "message": "test",
                    }
                },
            )
        if not scenario["complete"]:
            return httpx.Response(
                200,
                text='data: {"type":"response.output_text.delta","delta":"partial"}\n\n',
            )
        return httpx.Response(
            200,
            text="data: "
            + json.dumps(
                {
                    "type": "response.completed",
                    "response": {
                        "id": "resp_test",
                        "status": "completed",
                        "output": [
                            {
                                "content": [
                                    {
                                        "type": "output_text",
                                        "text": "# Borrador generado",
                                    }
                                ]
                            }
                        ],
                        "usage": {
                            "input_tokens": 100,
                            "output_tokens": 10,
                            "total_tokens": 110,
                        },
                    },
                }
            )
            + "\n\n",
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        connection = PlanConnection(
            client,
            tmp_path / "registration.json",
            "http://127.0.0.1:8766/auth/callback",
        )
        yield connection, scenario, requests


def begin(connection, scenario):
    query = parse_qs(urlparse(connection.authorize()).query)
    scenario["nonce"] = query["nonce"][0]
    return {"state": query["state"][0], "code": "test-code", "client_id": "oaiapp_test"}


def test_oauth_then_real_langgraph_saves_only_completed_result(provider, tmp_path):
    connection, scenario, requests = provider
    params = begin(connection, scenario)
    connection.finish(params)
    stages = []
    result, target = run_graph(
        connection,
        "test-model",
        tmp_path / "generated",
        lambda phase, *_: stages.append(phase),
    )
    assert stages[0] == "reading" and stages[-1] == "saving"
    assert "generating" in stages
    assert result["authentication"] == "chatgpt_plan_oauth"
    assert result["status"] == "awaiting_stuart_review"
    assert result["usage"]["total_tokens"] == 110
    assert (target / "preparation.md").read_text() == "# Borrador generado"
    assert len([r for r in requests if r.url.path == "/v1/responses"]) == 1
    saved = connection.registration_file.read_text()
    assert "oauth-test-access" not in saved and "id_token" not in saved
    assert connection.registration_file.stat().st_mode & 0o777 == 0o600
    with pytest.raises(DemoError):
        connection.finish(params)  # Callback cannot be replayed.


def test_wrong_state_does_not_exchange_code(provider):
    connection, scenario, requests = provider
    params = begin(connection, scenario)
    params["state"] = "wrong"
    with pytest.raises(DemoError, match="state"):
        connection.finish(params)
    assert not requests


@pytest.mark.parametrize(
    "claims",
    [
        {"nonce": "wrong"},
        {"iss": "https://other.example"},
        {"aud": "another-client"},
        {"exp": 1},
    ],
)
def test_invalid_identity_never_grants_inference(provider, claims):
    connection, scenario, requests = provider
    scenario["claims"] = claims
    with pytest.raises(DemoError, match="identidad"):
        connection.finish(begin(connection, scenario))
    assert connection.access_token is None
    assert not any(r.url.path == "/v1/models" for r in requests)


def test_identity_without_plan_scope_does_not_invoke_model(provider):
    connection, scenario, requests = provider
    scenario["scope"] = "openid profile email"
    with pytest.raises(DemoError, match="no habilitó"):
        connection.finish(begin(connection, scenario))
    assert connection.access_token is None
    assert not any(r.url.path == "/v1/responses" for r in requests)


def test_incomplete_stream_is_not_saved_or_claimed_as_success(provider, tmp_path):
    connection, scenario, _ = provider
    connection.finish(begin(connection, scenario))
    scenario["complete"] = False
    with pytest.raises(DemoError, match="sin confirmar el final"):
        run_graph(connection, "test-model", tmp_path / "generated")
    assert not (tmp_path / "generated").exists()


def sse(*events):
    return "".join(
        "event: " + event["type"] + "\ndata: " + json.dumps(event) + "\n\n"
        for event in events
    )


@pytest.mark.parametrize("status", ["completed", None])
def test_completed_metadata_does_not_need_to_repeat_streamed_text(
    provider, tmp_path, status
):
    connection, scenario, _ = provider
    connection.finish(begin(connection, scenario))
    scenario["wire"] = sse(
        {
            "type": "response.output_text.delta",
            "output_index": 0,
            "content_index": 0,
            "delta": "# Resumen\n",
        },
        {
            "type": "response.output_text.delta",
            "output_index": 0,
            "content_index": 0,
            "delta": "Necesidades del cliente.",
        },
        {
            "type": "response.output_text.done",
            "output_index": 0,
            "content_index": 0,
            "text": "# Resumen\nNecesidades del cliente.",
        },
        {
            "type": "response.completed",
            "response": {
                "id": "resp_test",
                "status": status,
                "output": [],
                "usage": {"total_tokens": 80},
            },
        },
    )
    result, _ = run_graph(connection, "test-model", tmp_path / "generated")
    assert result["draft"] == "# Resumen\nNecesidades del cliente."
    assert result["stream"]["terminal"] == "response.completed"
    assert result["stream"]["received_characters"] == len(result["draft"])


def test_done_marker_without_terminal_event_never_confirms_generation(
    provider, tmp_path
):
    connection, scenario, _ = provider
    connection.finish(begin(connection, scenario))
    scenario["wire"] = (
        sse({"type": "response.output_text.delta", "delta": "Texto parcial"})
        + "data: [DONE]\n\n"
    )
    with pytest.raises(DemoError, match="sin confirmar el final"):
        run_graph(connection, "test-model", tmp_path / "generated")
    assert connection.stream_text == "Texto parcial"
    assert connection.stream_diagnostic["terminal"] is None
    assert not (tmp_path / "generated").exists()


def test_late_subscription_error_is_not_mistaken_for_completion(provider, tmp_path):
    connection, scenario, _ = provider
    connection.finish(begin(connection, scenario))
    scenario["wire"] = sse(
        {"type": "response.output_text.delta", "delta": "Texto parcial"},
        {
            "type": "response.failed",
            "response": {
                "status": "failed",
                "error": {
                    "code": "subscription_sharing_usage_limit_exceeded",
                    "message": "test",
                },
            },
        },
    )
    with pytest.raises(DemoError, match="subscription_sharing_usage_limit_exceeded"):
        run_graph(connection, "test-model", tmp_path / "generated")
    assert connection.stream_text == "Texto parcial"
    assert not (tmp_path / "generated").exists()


def test_subscription_quota_error_has_no_retry_or_api_key_fallback(provider, tmp_path):
    connection, scenario, requests = provider
    connection.finish(begin(connection, scenario))
    scenario["rate_limit"] = True
    with pytest.raises(DemoError, match="subscription_sharing_usage_limit_exceeded"):
        run_graph(connection, "test-model", tmp_path / "generated")
    assert len([r for r in requests if r.url.path == "/v1/responses"]) == 1


def test_local_browser_flow_and_csrf(provider, tmp_path):
    connection, scenario, _ = provider
    app = create_app(connection, tmp_path / "generated")
    with TestClient(app, base_url="http://127.0.0.1:8766") as browser:
        assert browser.get("/status").status_code == 403
        page = browser.get("/")
        # A real HTML form sends Origin: null under no-referrer, even on a
        # same-origin POST. The page policy must preserve its local Origin.
        assert page.headers["referrer-policy"] == "same-origin"
        assert browser.post("/connect").status_code == 403
        csrf = re.search(r'name="csrf" value="([^"]+)"', page.text)[1]
        rejected = browser.post(
            "/connect", data={"csrf": csrf}, headers={"origin": "https://other.example"}
        )
        assert rejected.status_code == 403
        opaque = browser.post(
            "/connect", data={"csrf": csrf}, headers={"origin": "null"}
        )
        assert opaque.status_code == 403
        redirect = browser.post(
            "/connect",
            data={"csrf": csrf},
            headers={"origin": "http://127.0.0.1:8766"},
            follow_redirects=False,
        )
        query = parse_qs(urlparse(redirect.headers["location"]).query)
        assert query["client_id"] == ["dynamic_agent_client"]
        assert query["code_challenge_method"] == ["S256"]
        scenario["nonce"] = query["nonce"][0]
        callback = browser.get(
            "/auth/callback",
            params={
                "state": query["state"][0],
                "code": "test-code",
                "client_id": "oaiapp_test",
            },
            follow_redirects=False,
        )
        assert callback.headers["referrer-policy"] == "no-referrer"
        ready = browser.get("/status").json()
        assert ready["phase"] == "ready" and not ready["busy"]
        assert ready["connected"]
        browser.post(
            "/run",
            data={"csrf": csrf, "model": "test-model"},
            headers={"origin": "http://127.0.0.1:8766"},
        )
        result = browser.get("/status")
        assert result.json()["phase"] == "complete"
        assert not result.json()["busy"]
        assert "Borrador generado" in result.json()["draft"]
        assert "oauth-test-access" not in result.text
        assert "refresh_token" not in result.text
