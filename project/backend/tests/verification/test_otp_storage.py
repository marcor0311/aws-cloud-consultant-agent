"""OTP storage preserves rollback and exposes detached plain records to the service."""

import pytest

from app.verification.repository import SQLiteVerificationRepository


def test_failed_transaction_rolls_back_session_and_counters(tmp_path):
    repository = SQLiteVerificationRepository(tmp_path / "otp.sqlite3")
    with pytest.raises(RuntimeError):
        with repository.transaction() as transaction:
            transaction.create_session(
                "call", "voice", "client@example.test", "AAAA-0001"
            )
            transaction.record_event(
                "client@example.test", "voice", "call", "send", 100
            )
            raise RuntimeError("Abort before committing")
    assert repository.get("call") is None
    with repository.transaction() as transaction:
        assert transaction.latest_send("client@example.test", "call") is None


def test_restarted_repository_returns_plain_detached_session_data(tmp_path):
    database = tmp_path / "otp.sqlite3"
    repository = SQLiteVerificationRepository(database)
    with repository.transaction() as transaction:
        transaction.create_session("call", "voice", "client@example.test", "AAAA-0001")
        transaction.save_challenge("challenge", "only-the-digest", 500, "call")
    restarted = SQLiteVerificationRepository(database)
    state = restarted.get("call")
    assert type(state) is dict
    assert state["state"] == "sending"
    state["state"] = "verified"
    assert restarted.get("call")["state"] == "sending"
