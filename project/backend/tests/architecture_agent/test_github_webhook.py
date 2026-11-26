"""GitHub webhook evidence is authenticated but never treated as approval."""

import hashlib
import hmac
import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import get_runtime
from app.api.webhooks import router


class ObservedProcess:
    def __init__(self):
        self.calls = []

    def observe_github(self, *args):
        self.calls.append(args)
        return {"status": "accepted", "linked_phases": 1}


class ObservedArchitecture:
    def __init__(self):
        self.calls = []

    def observe_github_event(self, *args):
        self.calls.append(args)
        return {"status": "linked", "approved": False}


class ObservedFinOps:
    def __init__(self):
        self.calls = []

    def observe_github_event(self, *args):
        self.calls.append(args)
        return {"status": "linked", "transitioned": False}


def signed_headers(secret, payload, event, delivery="delivery-1"):
    raw = json.dumps(payload, separators=(",", ":")).encode()
    signature = "sha256=" + hmac.new(
        secret.encode(), raw, hashlib.sha256
    ).hexdigest()
    return raw, {
        "x-hub-signature-256": signature,
        "x-github-delivery": delivery,
        "x-github-event": event,
        "content-type": "application/json",
    }


def test_signed_review_and_check_webhooks_are_observed_without_approval():
    secret = "s" * 32
    process = ObservedProcess()
    architecture = ObservedArchitecture()
    finops = ObservedFinOps()
    runtime = SimpleNamespace(
        settings=SimpleNamespace(
            github_secret=secret, github_repositories=["example/project"]
        ),
        process=process,
        architecture=architecture,
        finops=finops,
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    client = TestClient(app)
    pull_url = "https://github.com/example/project/pull/7"
    review = {
        "action": "submitted",
        "repository": {"full_name": "example/project"},
        "pull_request": {"html_url": pull_url, "created_at": "2026-11-25T18:00:00Z"},
        "review": {"state": "approved"},
    }
    raw, headers = signed_headers(secret, review, "pull_request_review")
    response = client.post("/workflow/events/github", content=raw, headers=headers)
    assert response.status_code == 202
    assert response.json()["architecture"]["approved"] is False

    checks = {
        "action": "completed",
        "repository": {"full_name": "example/project"},
        "check_suite": {
            "pull_requests": [{"html_url": pull_url}],
            "conclusion": "success",
        },
    }
    raw, headers = signed_headers(secret, checks, "check_suite", "delivery-2")
    assert client.post("/workflow/events/github", content=raw, headers=headers).status_code == 202

    assert [call[2] for call in process.calls] == [
        "pull_request_review",
        "check_suite",
    ]
    assert all(call[1] == pull_url for call in process.calls)
    assert [call[2] for call in architecture.calls] == [
        "pull_request_review",
        "check_suite",
    ]
    assert [call[2] for call in finops.calls] == [
        "pull_request_review",
        "check_suite",
    ]
    assert response.json()["finops"]["transitioned"] is False
    # observe_github records evidence only; it has no approval transition argument.
    assert all(len(call) == 7 for call in process.calls)


def test_github_webhook_rejects_invalid_signature():
    runtime = SimpleNamespace(
        settings=SimpleNamespace(
            github_secret="s" * 32, github_repositories=["example/project"]
        ),
        process=ObservedProcess(),
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    response = TestClient(app).post(
        "/workflow/events/github",
        json={"repository": {"full_name": "example/project"}},
        headers={
            "x-hub-signature-256": "sha256=" + "0" * 64,
            "x-github-delivery": "delivery-invalid",
            "x-github-event": "pull_request",
        },
    )
    assert response.status_code == 401
