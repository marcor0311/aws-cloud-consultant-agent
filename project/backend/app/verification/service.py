"""Persistent one-time verification with pre-registered clients."""

import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from app.clients.domain import (
    ClientRegistry,
    RegistryUnavailable,
    normalize_client_code,
)
from app.core.validation import normalize_email
from app.verification.ports import VerificationRepository

REGISTRATION_MESSAGE = (
    "Para continuar, debe hablar con un asesor de negocio para completar su registro."
)


class CodeMailer(Protocol):
    def send_code(self, email: str, name: str, code: str, minutes: int) -> None: ...


@dataclass(frozen=True)
class AccessPolicy:
    code_ttl: int = 300
    authorization_ttl: int = 1800
    max_attempts: int = 5
    resend_cooldown: int = 60
    send_window: int = 3600
    sends_per_email: int = 5
    sends_per_origin: int = 10
    failure_window: int = 900
    failures_per_identity: int = 10


@dataclass
class CalendarAccessService:
    repository: VerificationRepository
    secret: str = field(repr=False)
    mailer: CodeMailer = field(repr=False)
    clients: ClientRegistry = field(repr=False)
    policy: AccessPolicy = field(default_factory=AccessPolicy)
    clock: Callable[[], float] = field(default=time.time, repr=False)

    def __post_init__(self):
        if len(self.secret) < 32:
            raise ValueError(
                "CALENDAR_ACCESS_CODE_SECRET debe tener al menos 32 caracteres."
            )

    def _registration(self, email, client_code):
        contact = self.clients.lookup_code(client_code) if client_code else None
        return contact if contact and contact.company_email == email else None

    def _digest(self, session_id, email, challenge_id, code):
        message = json.dumps([session_id, email, challenge_id, code]).encode()
        return hmac.new(self.secret.encode(), message, hashlib.sha256).hexdigest()

    def _limited(self, db, session, kind, window, email_limit, origin_limit, now):
        rows = db.recent_events(
            kind, now - window, session["email"], session["origin_id"]
        )
        return (
            sum(row["email"] == session["email"] for row in rows) >= email_limit
            or sum(row["origin_id"] == session["origin_id"] for row in rows)
            >= origin_limit
        )

    @staticmethod
    def _event(db, session, kind, now):
        db.record_event(
            session["email"], session["origin_id"], session["session_id"], kind, now
        )

    def start(self, session_id: str, client_code: str, origin_id: str) -> dict:
        client_code = normalize_client_code(client_code)
        # Revoke the previous identity even when the new code is unknown or storage fails.
        with self.repository.transaction() as db:
            session = db.get(session_id)
            if session and session["state"] == "closed":
                return {"status": "session_closed"}
            if session and session["origin_id"] != origin_id:
                return {"status": "invalid_session"}
            if session and (
                session["client_code"] != client_code or session["state"] == "verified"
            ):
                db.revoke(session_id)
        try:
            client = self.clients.lookup_code(client_code)
        except RegistryUnavailable:
            return {"status": "unavailable"}
        if not client or not client.enabled:
            with self.repository.transaction() as db:
                db.revoke(session_id)
            return {
                "status": "not_registered" if not client else "not_enabled",
                "message": REGISTRATION_MESSAGE,
            }
        return self._issue(
            session_id, client.company_email, origin_id, client_code=client_code
        )

    def resend(self, session_id: str, challenge_id: str) -> dict:
        return self._issue(session_id, previous_challenge=challenge_id)

    def _issue(
        self,
        session_id,
        email=None,
        origin_id=None,
        previous_challenge=None,
        client_code=None,
    ):
        now = self.clock()
        policy = self.policy
        with self.repository.transaction() as db:
            session = db.get(session_id)
            if session and session["state"] == "closed":
                return {"status": "session_closed"}
            if previous_challenge is not None:
                if (
                    not session
                    or session["challenge_id"] != previous_challenge
                    or session["state"] not in {"sent", "expired", "locked"}
                ):
                    return {"status": "verification_required"}
                email, origin_id = session["email"], session["origin_id"]
                client_code = session["client_code"]
            if session and session["origin_id"] != origin_id:
                return {"status": "invalid_session"}
            if not session:
                db.create_session(session_id, origin_id, email, client_code)
            elif (
                session["email"] != email
                or session["client_code"] != client_code
                or session["state"] == "verified"
            ):
                # A new identity or new verification request revokes authorization.
                db.change_identity(email, client_code, session_id)
        lookup_failed = False
        try:
            registration = self._registration(email, client_code)
        except RegistryUnavailable:
            registration, lookup_failed = None, True
        with self.repository.transaction() as db:
            session = db.get(session_id)
            if (
                not session
                or session["state"] == "closed"
                or session["email"] != email
                or session["client_code"] != client_code
            ):
                return {"status": "verification_required"}
            if (
                previous_challenge is not None
                and session["challenge_id"] != previous_challenge
            ):
                return {"status": "verification_required"}
            if lookup_failed:
                db.revoke(session_id)
                return {"status": "unavailable"}
            if not registration or not registration.enabled:
                db.revoke(session_id)
                return {
                    "status": "not_registered" if not registration else "not_enabled",
                    "message": REGISTRATION_MESSAGE,
                }
            now = self.clock()
            # Retain rate-limit counters across challenges, calls and process restarts.
            db.prune_events(now - 86400)
            latest = db.latest_send(email, session_id)
            if latest is not None and now - latest < policy.resend_cooldown:
                return {
                    "status": "rate_limited",
                    "retry_after_seconds": max(
                        1, int(policy.resend_cooldown - (now - latest))
                    ),
                }
            if self._limited(
                db,
                session,
                "send",
                policy.send_window,
                policy.sends_per_email,
                policy.sends_per_origin,
                now,
            ):
                return {
                    "status": "rate_limited",
                    "retry_after_seconds": policy.send_window,
                }
            code = f"{secrets.randbelow(1_000_000):06d}"
            challenge_id = secrets.token_urlsafe(32)
            expires = now + policy.code_ttl
            db.save_challenge(
                challenge_id,
                self._digest(session_id, email, challenge_id, code),
                expires,
                session_id,
            )
            self._event(db, session, "send", now)
        # SMTP delivery never holds the database write lock. Pending codes cannot verify.
        try:
            self.mailer.send_code(
                email, registration.company_name, code, policy.code_ttl // 60
            )
        except Exception:
            with self.repository.transaction() as db:
                db.cancel_sending(session_id, challenge_id)
            return {
                "status": "unavailable",
                "message": "No pude enviar el código. Intente de nuevo más tarde.",
            }
        with self.repository.transaction() as db:
            updated = db.confirm_sent(session_id, challenge_id)
        if not updated:
            return {"status": "verification_required"}
        return {
            "status": "code_sent",
            "challenge_id": challenge_id,
            "expires_in_seconds": max(0, int(expires - self.clock())),
        }

    def verify(self, session_id: str, challenge_id: str, code: str) -> dict:
        policy = self.policy
        snapshot = self.repository.get(session_id)
        if not snapshot or snapshot["state"] in {"empty", "sending", "verified"}:
            return {"status": "verification_required"}
        if snapshot["state"] == "closed":
            return {"status": "session_closed"}
        try:
            registration = self._registration(
                snapshot["email"], snapshot["client_code"]
            )
        except RegistryUnavailable:
            return {"status": "unavailable"}
        with self.repository.transaction() as db:
            now = self.clock()
            session = db.get(session_id)
            if (
                not session
                or session["state"] in {"empty", "sending", "verified"}
                or session["email"] != snapshot["email"]
                or session["client_code"] != snapshot["client_code"]
            ):
                return {"status": "verification_required"}
            if session["state"] == "closed":
                return {"status": "session_closed"}
            if not registration or not registration.enabled:
                db.revoke(session_id)
                return {"status": "not_enabled", "message": REGISTRATION_MESSAGE}
            if session["attempts"] >= policy.max_attempts or self._limited(
                db,
                session,
                "failure",
                policy.failure_window,
                policy.failures_per_identity,
                policy.failures_per_identity,
                now,
            ):
                return {"status": "attempts_exceeded"}
            if session["code_expires"] <= now:
                db.expire(session_id)
                return {"status": "expired"}
            valid = (
                session["challenge_id"] == challenge_id
                and session["code_digest"] is not None
                and hmac.compare_digest(
                    session["code_digest"],
                    self._digest(session_id, session["email"], challenge_id, code),
                )
            )
            if not valid:
                attempts = session["attempts"] + 1
                locked = attempts >= policy.max_attempts
                db.set_attempts(attempts, "locked" if locked else "sent", session_id)
                self._event(db, session, "failure", now)
                return {
                    "status": "attempts_exceeded" if locked else "invalid_code",
                    "attempts_remaining": max(0, policy.max_attempts - attempts),
                }
            until = now + policy.authorization_ttl
            db.mark_verified(until, session_id)
            return {
                "status": "verified",
                "email": session["email"],
                "expires_in_seconds": policy.authorization_ttl,
            }

    def authorize(self, session_id: str, email: str) -> dict:
        snapshot = self.repository.get(session_id)
        if not snapshot or snapshot["state"] != "verified":
            return {"status": "verification_required"}
        try:
            registration = self._registration(
                snapshot["email"], snapshot["client_code"]
            )
        except RegistryUnavailable:
            return {"status": "unavailable"}
        with self.repository.transaction() as db:
            session = db.get(session_id)
            if (
                not session
                or session["state"] != "verified"
                or session["email"] != snapshot["email"]
                or session["client_code"] != snapshot["client_code"]
            ):
                return {"status": "verification_required"}
            if not registration or not registration.enabled:
                db.revoke(session_id)
                return {"status": "not_enabled", "message": REGISTRATION_MESSAGE}
            if session["email"] != normalize_email(email):
                return {"status": "email_mismatch"}
            if session["verified_until"] <= self.clock():
                return {"status": "expired"}
            return {"status": "authorized", "email": session["email"]}

    def close(self, session_id: str) -> dict:
        with self.repository.transaction() as db:
            db.close(session_id)
        return {"status": "closed"}
