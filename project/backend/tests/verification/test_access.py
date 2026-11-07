import itertools
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.calendar_access import get_access_service, router
from app.clients.domain import Client, RegistryUnavailable
from app.notifications.smtp import SMTPMailer, SMTPSettings
from app.verification.repository import SQLiteVerificationRepository
from app.verification.service import AccessPolicy, CalendarAccessService

EMAIL = "cliente@example.com"
SESSION = "call_1234567890123456"
OTHER_SESSION = "call_9876543210987654"
KEY = "service-key-for-testing-only-1234567890"
SECRET = "code-secret-for-testing-only-1234567890"


class Mailbox:
    def __init__(self):
        self.messages = []
        self.fail = False
        self.on_send = None

    def send_code(self, email, name, code, minutes):
        if self.fail:
            raise OSError("SMTP unavailable")
        if self.on_send:
            self.on_send()
        self.messages.append((email, name, code, minutes))

    @property
    def code(self):
        return self.messages[-1][2]


CODES = {
    EMAIL: "IOAA-0012",
    "otra@example.com": "BBBB-0000",
    "third@example.com": "CCCC-3333",
    "missing@example.com": "ZZZZ-9999",
}


def RegisteredContact(name, enabled, email=EMAIL):
    return Client(1, CODES[email], name, email, enabled)


class FakeRegistry:
    def __init__(self):
        self.contacts = {
            EMAIL: RegisteredContact("Persona registrada", True),
            "otra@example.com": RegisteredContact(
                "Otra persona", True, "otra@example.com"
            ),
        }
        self.fail = False

    def lookup_code(self, code):
        if self.fail:
            raise RegistryUnavailable()
        return next(
            (
                contact
                for contact in self.contacts.values()
                if contact.client_code == code
            ),
            None,
        )

    def lookup(self, email):
        if self.fail:
            raise RegistryUnavailable()
        return self.contacts.get(email)


@pytest.fixture
def service(tmp_path, monkeypatch):
    numbers = itertools.count(1)
    monkeypatch.setattr(
        "app.verification.service.secrets.randbelow", lambda _: next(numbers)
    )
    now = [2_000_000_000.0]
    instance = CalendarAccessService(
        SQLiteVerificationRepository(tmp_path / "access.sqlite3"),
        SECRET,
        Mailbox(),
        FakeRegistry(),
        clock=lambda: now[0],
    )
    instance.test_clock = now
    return instance


def begin(service, session=SESSION, email=EMAIL, origin="trusted-caller"):
    return service.start(session, CODES[email.strip().lower()], origin)


def verify(service, challenge, session=SESSION, code=None):
    return service.verify(
        session, challenge["challenge_id"], code or service.mailer.code
    )


def test_registered_caller_is_authorized_only_after_code_and_bound_to_email(service):
    assert service.authorize(SESSION, EMAIL)["status"] == "verification_required"
    challenge = begin(service, email=" CLIENTE@EXAMPLE.COM ")
    assert challenge["status"] == "code_sent"
    assert service.mailer.code == "000001"
    assert service.mailer.code not in str(challenge)
    assert service.authorize(SESSION, EMAIL)["status"] == "verification_required"
    assert verify(service, challenge)["status"] == "verified"
    assert service.authorize(SESSION, EMAIL)["status"] == "authorized"
    assert service.authorize(SESSION, "otra@example.com")["status"] == "email_mismatch"
    assert service.authorize(OTHER_SESSION, EMAIL)["status"] == "verification_required"


@pytest.mark.parametrize("disabled", [False, True])
def test_unregistered_or_disabled_caller_gets_advisor_message_without_email(
    service, disabled
):
    email = "missing@example.com"
    if disabled:
        service.clients.contacts[email] = RegisteredContact("Persona", False, email)
    response = begin(service, email=email)
    assert response["status"] == ("not_enabled" if disabled else "not_registered")
    assert "asesor de negocio" in response["message"]
    assert service.mailer.messages == []


def test_backend_outage_is_not_misreported_as_non_registration(service):
    service.clients.fail = True
    assert begin(service)["status"] == "unavailable"
    assert not service.mailer.messages


def test_code_is_single_use_and_does_not_extend_existing_authorization(service):
    challenge = begin(service)
    assert verify(service, challenge)["status"] == "verified"
    service.test_clock[0] += 1700
    assert verify(service, challenge)["status"] == "verification_required"
    service.test_clock[0] += 101
    assert service.authorize(SESSION, EMAIL)["status"] == "expired"


def test_wrong_attempts_lock_challenge(service):
    challenge = begin(service)
    for remaining in (4, 3, 2, 1):
        result = verify(service, challenge, code="999999")
        assert result == {"status": "invalid_code", "attempts_remaining": remaining}
    assert verify(service, challenge, code="999999")["status"] == "attempts_exceeded"
    assert verify(service, challenge)["status"] == "attempts_exceeded"


def test_resend_has_cooldown_and_invalidates_previous_code(service):
    original = begin(service)
    old_code = service.mailer.code
    assert service.resend(SESSION, original["challenge_id"])["status"] == "rate_limited"
    service.test_clock[0] += 61
    replacement = service.resend(SESSION, original["challenge_id"])
    assert replacement["status"] == "code_sent"
    assert replacement["challenge_id"] != original["challenge_id"]
    assert verify(service, original, code=old_code)["status"] == "invalid_code"
    assert verify(service, replacement, code=old_code)["status"] == "invalid_code"
    assert verify(service, replacement)["status"] == "verified"


def test_expired_code_can_only_be_replaced_not_used(service):
    challenge = begin(service)
    service.test_clock[0] += 301
    assert verify(service, challenge)["status"] == "expired"
    assert service.resend(SESSION, challenge["challenge_id"])["status"] == "code_sent"


def test_changing_client_code_revokes_authorization_even_if_unknown(
    service,
):
    challenge = begin(service)
    verify(service, challenge)
    assert begin(service, email="missing@example.com")["status"] == "not_registered"
    assert service.authorize(SESSION, EMAIL)["status"] == "verification_required"
    assert verify(service, challenge)["status"] == "verification_required"


def test_disabling_registration_revokes_session(
    service,
):
    challenge = begin(service)
    verify(service, challenge)
    service.clients.contacts[EMAIL] = RegisteredContact("Persona", False)
    assert service.authorize(SESSION, EMAIL)["status"] == "not_enabled"
    service.clients.contacts[EMAIL] = RegisteredContact("Persona", True)
    assert service.authorize(SESSION, EMAIL)["status"] == "verification_required"
    with sqlite3.connect(service.repository.database) as db:
        tables = {
            row[0]
            for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "calendar_registry" not in tables


def test_failure_to_send_never_leaves_a_usable_code(service):
    service.mailer.fail = True
    assert begin(service)["status"] == "unavailable"
    assert service.authorize(SESSION, EMAIL)["status"] == "verification_required"
    with sqlite3.connect(service.repository.database) as db:
        assert (
            db.execute("SELECT code_digest FROM calendar_sessions").fetchone()[0]
            is None
        )


def test_no_plaintext_code_is_persisted(service):
    begin(service)
    with sqlite3.connect(service.repository.database) as db:
        dump = "\n".join(db.iterdump())
        assert service.mailer.code not in dump


def test_session_cannot_be_reopened_after_close(service):
    challenge = begin(service)
    verify(service, challenge)
    service.close(SESSION)
    assert service.authorize(SESSION, EMAIL)["status"] == "verification_required"
    assert begin(service)["status"] == "session_closed"


def test_sessions_and_limits_survive_restart(service):
    challenge = begin(service)
    verify(service, challenge)
    restarted = CalendarAccessService(
        SQLiteVerificationRepository(service.repository.database),
        SECRET,
        service.mailer,
        service.clients,
        clock=service.clock,
    )
    assert restarted.authorize(SESSION, EMAIL)["status"] == "authorized"
    assert begin(restarted, session=OTHER_SESSION)["status"] == "rate_limited"


def test_email_rate_limit_applies_across_new_calls_and_origins(service):
    for number in range(5):
        assert (
            begin(service, session=f"session_{number:016}", origin=f"origin_{number}")[
                "status"
            ]
            == "code_sent"
        )
        service.test_clock[0] += 61
    assert (
        begin(service, session=OTHER_SESSION, origin="new_origin")["status"]
        == "rate_limited"
    )


def test_origin_rate_limit_applies_across_different_emails(service):
    service.policy = AccessPolicy(sends_per_origin=2)
    begin(service)
    begin(service, session=OTHER_SESSION, email="otra@example.com")
    service.clients.contacts["third@example.com"] = RegisteredContact(
        "Third", True, "third@example.com"
    )
    assert (
        begin(service, session="third_call_123456789", email="third@example.com")[
            "status"
        ]
        == "rate_limited"
    )


def test_failure_budget_cannot_be_reset_with_new_challenges(service):
    service.policy = AccessPolicy(failures_per_identity=3)
    challenge = begin(service)
    for _ in range(3):
        verify(service, challenge, code="999999")
    service.test_clock[0] += 61
    challenge = begin(service, session=OTHER_SESSION)
    assert (
        verify(service, challenge, session=OTHER_SESSION)["status"]
        == "attempts_exceeded"
    )


def test_concurrent_replay_only_verifies_once(service):
    challenge = begin(service)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: verify(service, challenge), range(2)))
    assert sorted(result["status"] for result in results) == [
        "verification_required",
        "verified",
    ]


def test_pending_email_cannot_verify_and_does_not_hold_write_lock(service):
    def inspect_pending():
        with sqlite3.connect(service.repository.database) as db:
            challenge = db.execute(
                "SELECT challenge_id FROM calendar_sessions"
            ).fetchone()[0]
        assert (
            service.verify(SESSION, challenge, "000001")["status"]
            == "verification_required"
        )
        service.close(SESSION)

    service.mailer.on_send = inspect_pending
    assert begin(service)["status"] == "verification_required"
    assert service.authorize(SESSION, EMAIL)["status"] == "verification_required"


@pytest.fixture
def api(service, monkeypatch):
    monkeypatch.setenv("CALENDAR_ACCESS_SERVICE_KEY", KEY)
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_access_service] = lambda: service
    return TestClient(app)


def test_api_requires_service_key_and_exposes_no_registry_management(api):
    data = {
        "session_id": SESSION,
        "client_code": CODES[EMAIL],
        "origin_id": "trusted-caller",
    }
    assert api.post("/api/calendar-access/start", json=data).status_code == 401
    assert (
        api.post(
            "/api/calendar-access/start",
            json=data,
            headers={"Authorization": "Bearer wrong"},
        ).status_code
        == 401
    )
    assert api.put("/api/calendar-access/registry", json={}).status_code == 404


def test_api_full_verification_round_trip(api, service):
    headers = {"Authorization": f"Bearer {KEY}"}
    response = api.post(
        "/api/calendar-access/start",
        headers=headers,
        json={
            "session_id": SESSION,
            "client_code": CODES[EMAIL],
            "origin_id": "trusted-caller",
        },
    )
    assert response.status_code == 200
    challenge = response.json()
    response = api.post(
        "/api/calendar-access/verify",
        headers=headers,
        json={
            "session_id": SESSION,
            "challenge_id": challenge["challenge_id"],
            "code": service.mailer.code,
        },
    )
    assert response.json()["status"] == "verified"
    assert service.mailer.code not in response.text
    response = api.post(
        "/api/calendar-access/authorize",
        headers=headers,
        json={"session_id": SESSION, "email": EMAIL, "operation": "book"},
    )
    assert response.json()["status"] == "authorized"


def test_api_fails_closed_without_configuration(api, monkeypatch):
    monkeypatch.delenv("CALENDAR_ACCESS_SERVICE_KEY")
    response = api.post("/api/calendar-access/close", json={"session_id": SESSION})
    assert response.status_code == 503


def test_email_template_has_text_and_html_without_branding_or_call_context():
    mailer = SMTPMailer(
        SMTPSettings("smtp.example.test", 587, "user", "password", "sender@example.com")
    )
    message = mailer.build_message(EMAIL, "<script>{{code}}</script>", "003120", 5)
    text = message.get_body(preferencelist=("plain",)).get_content()
    rendered = message.get_body(preferencelist=("html",)).get_content()
    assert "003120" in text and "003120" in rendered
    assert "5 minutos" in rendered
    assert "<script>" not in rendered
    for content in (rendered, text, str(message["Subject"]), str(message["From"])):
        for forbidden in (
            "Futura",
            "Alisa",
            "Stuart",
            "llamada",
            "<script>",
            "{{code}}",
        ):
            assert forbidden not in content
    assert str(message["Subject"]) == "Código de verificación"


def test_start_rejects_alternative_email_and_invalid_client_code(api):
    headers = {"Authorization": f"Bearer {KEY}"}
    data = {"session_id": SESSION, "client_code": "IOAA-0012", "origin_id": "test"}
    assert (
        api.post(
            "/api/calendar-access/start",
            headers=headers,
            json={**data, "email": "attacker@example.com"},
        ).status_code
        == 422
    )
    for code in ("ABÑD-1234", "ABCD-123", "ABCD-12345", "cliente@example.com"):
        assert (
            api.post(
                "/api/calendar-access/start",
                headers=headers,
                json={**data, "client_code": code},
            ).status_code
            == 422
        )


def test_starting_disabled_client_revokes_pending_challenge(service):
    challenge = begin(service)
    service.clients.contacts[EMAIL] = RegisteredContact("Empresa", False)
    assert begin(service)["status"] == "not_enabled"
    service.clients.contacts[EMAIL] = RegisteredContact("Empresa", True)
    assert verify(service, challenge)["status"] == "verification_required"


def test_same_pending_client_can_retry_start_without_losing_otp(service):
    challenge = begin(service)
    assert begin(service)["status"] == "rate_limited"
    assert verify(service, challenge)["status"] == "verified"
