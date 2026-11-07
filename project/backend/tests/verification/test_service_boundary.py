"""Authorization rules work without SQLite, a web app or a graph engine."""

from contextlib import contextmanager
from types import SimpleNamespace

from app.clients.domain import Client
from app.verification.service import CalendarAccessService


class Sessions:
    def __init__(self):
        self.state = {
            "state": "verified",
            "email": "client@example.test",
            "client_code": "AAAA-0001",
            "verified_until": 200,
        }

    def get(self, _session_id):
        return dict(self.state)

    @contextmanager
    def transaction(self):
        yield self

    def revoke(self, _session_id):
        self.state["state"] = "empty"


def test_disabled_client_revokes_authorization_through_the_storage_contract():
    repository = Sessions()
    registry = SimpleNamespace(
        lookup_code=lambda _: Client(
            1, "AAAA-0001", "Fixture", "client@example.test", True
        )
    )
    service = CalendarAccessService(
        repository, "fixture-" * 5, None, registry, clock=lambda: 100
    )
    assert service.authorize("call", "client@example.test")["status"] == "authorized"
    registry.lookup_code = lambda _: Client(
        1, "AAAA-0001", "Fixture", "client@example.test", False
    )
    assert service.authorize("call", "client@example.test")["status"] == "not_enabled"
    registry.lookup_code = lambda _: Client(
        1, "AAAA-0001", "Fixture", "client@example.test", True
    )
    assert (
        service.authorize("call", "client@example.test")["status"]
        == "verification_required"
    )
