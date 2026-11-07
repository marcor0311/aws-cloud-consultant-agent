import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest

from app.clients import domain as clients
from app.clients.domain import RegistryUnavailable
from app.clients.repository import ClientRepository
from app.verification.repository import SQLiteVerificationRepository
from app.verification.service import CalendarAccessService


def test_server_generates_code_with_repeats_i_o_and_leading_zeroes(monkeypatch):
    letters = iter("IIOO")
    monkeypatch.setattr(clients.secrets, "choice", lambda _: next(letters))
    monkeypatch.setattr(clients.secrets, "randbelow", lambda _: 12)
    assert clients.generate_client_code() == "IIOO-0012"


def test_creation_persists_generated_ids_and_retries_collisions(tmp_path, monkeypatch):
    repo = ClientRepository(tmp_path / "clients.sqlite3")
    generate = Mock(side_effect=["AAAA-0000", "AAAA-0000", "IOIO-0012"])
    monkeypatch.setattr(clients, "generate_client_code", generate)
    first = repo.create(" Empresa uno ", " FIRST@example.com ")
    second = repo.create("Empresa dos", "second@example.com")
    assert first.client_id != second.client_id
    assert first.company_name == "Empresa uno"
    assert first.company_email == "first@example.com"
    assert second.client_code == "IOIO-0012"
    assert generate.call_count == 3
    restarted = ClientRepository(repo.database)
    assert restarted.lookup_code("ioio-0012") == second
    assert restarted.lookup("FIRST@example.com") == first
    assert restarted.lookup_code("ZZZZ-9999") is None
    assert repo.database.stat().st_mode & 0o777 == 0o600


def test_database_enforces_unique_codes_and_email(tmp_path):
    repo = ClientRepository(tmp_path / "clients.sqlite3")
    company = repo.create("Empresa", "a@example.com")
    with sqlite3.connect(repo.database) as db:
        for code, email in (
            (company.client_code, "b@example.com"),
            ("BBBB-0000", "A@example.com"),
        ):
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(
                    "INSERT INTO clients(client_code, company_name, company_email) VALUES (?, 'Otra', ?)",
                    (code, email),
                )
    with pytest.raises(ValueError, match="ya está registrado"):
        repo.create("Otra", "a@example.com")


@pytest.mark.parametrize(
    "code", ["ABÑD-1234", "ABCDE-1234", "ABCD-123", "ABCD-１２３４", "ABCD-12345"]
)
def test_database_and_lookup_reject_invalid_code(tmp_path, code):
    repo = ClientRepository(tmp_path / "clients.sqlite3")
    with pytest.raises(ValueError):
        repo.lookup_code(code)
    with sqlite3.connect(repo.database) as db, pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO clients(client_code, company_name, company_email) VALUES (?, 'Empresa', 'a@example.com')",
            (code,),
        )


def test_concurrent_creations_use_distinct_ids_and_codes(tmp_path):
    repo = ClientRepository(tmp_path / "clients.sqlite3")
    with ThreadPoolExecutor(max_workers=6) as pool:
        records = list(
            pool.map(
                lambda i: repo.create(f"Empresa {i}", f"test{i}@example.com"), range(30)
            )
        )
    assert len({record.client_id for record in records}) == 30
    assert len({record.client_code for record in records}) == 30
    assert all(
        re.fullmatch(r"[A-Z]{4}-[0-9]{4}", record.client_code) for record in records
    )


def test_storage_failure_is_distinct_from_unknown_client(tmp_path):
    repo = ClientRepository(tmp_path / "clients.sqlite3")
    with sqlite3.connect(repo.database) as db:
        db.execute("DROP TABLE clients")
    with pytest.raises(RegistryUnavailable):
        repo.lookup_code("ABCD-1234")


@pytest.mark.parametrize("stage", ["verify", "resend", "authorize"])
def test_changing_approved_email_never_sends_or_authorizes_other_address(
    tmp_path, stage
):
    repo = ClientRepository(tmp_path / "clients.sqlite3")
    company = repo.create("Empresa", "approved@example.com")
    mailer = Mock()
    now = [2_000_000_000.0]
    service = CalendarAccessService(
        SQLiteVerificationRepository(repo.database),
        "independent-test-secret-1234567890123456",
        mailer,
        repo,
        clock=lambda: now[0],
    )
    challenge = service.start("session-client-1234567890", company.client_code, "test")
    assert challenge["status"] == "code_sent"
    assert "approved@example.com" not in str(challenge)
    assert mailer.send_code.call_args.args[0] == "approved@example.com"
    otp = mailer.send_code.call_args.args[2]
    if stage == "authorize":
        assert (
            service.verify("session-client-1234567890", challenge["challenge_id"], otp)[
                "status"
            ]
            == "verified"
        )
    with sqlite3.connect(repo.database) as db:
        db.execute("UPDATE clients SET company_email='changed@example.com'")
    if stage == "verify":
        result = service.verify(
            "session-client-1234567890", challenge["challenge_id"], otp
        )
    elif stage == "resend":
        now[0] += 61
        result = service.resend("session-client-1234567890", challenge["challenge_id"])
    else:
        result = service.authorize("session-client-1234567890", company.company_email)
    assert result["status"] == (
        "not_registered" if stage == "resend" else "not_enabled"
    )
    assert mailer.send_code.call_count == 1


def test_migrating_legacy_sessions_revokes_authorization_but_retains_send_limits(
    tmp_path,
):
    database = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(database) as db:
        db.execute(
            "CREATE TABLE calendar_sessions (session_id TEXT PRIMARY KEY, origin_id TEXT NOT NULL, email TEXT NOT NULL, challenge_id TEXT, code_digest TEXT, code_expires REAL, attempts INTEGER NOT NULL DEFAULT 0, verified_until REAL, state TEXT NOT NULL DEFAULT 'empty')"
        )
        db.execute(
            "INSERT INTO calendar_sessions(session_id, origin_id, email, state, verified_until, code_digest) VALUES ('old-session', 'test', 'a@example.com', 'verified', 9999999999, 'old-digest')"
        )
    repo = ClientRepository(database)
    service = CalendarAccessService(
        SQLiteVerificationRepository(database),
        "independent-test-secret-1234567890123456",
        Mock(),
        repo,
    )
    assert (
        service.authorize("old-session", "a@example.com")["status"]
        == "verification_required"
    )
    with sqlite3.connect(database) as db:
        assert db.execute(
            "SELECT client_code, code_digest, verified_until FROM calendar_sessions"
        ).fetchone() == (None, None, None)
