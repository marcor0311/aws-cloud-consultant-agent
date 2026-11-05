"""Persistent one-time verification with an independent whitelist repository."""

import hashlib
import hmac
import json
import secrets
import sqlite3
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from app.models.calendar_access import normalize_email
from app.services.calendar_whitelist import Whitelist, WhitelistUnavailable

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
    database: Path
    secret: str = field(repr=False)
    mailer: CodeMailer = field(repr=False)
    whitelist: Whitelist = field(repr=False)
    policy: AccessPolicy = field(default_factory=AccessPolicy)
    clock: Callable[[], float] = field(default=time.time, repr=False)

    def __post_init__(self):
        if len(self.secret) < 32:
            raise ValueError(
                "CALENDAR_ACCESS_CODE_SECRET debe tener al menos 32 caracteres."
            )
        self.database = Path(self.database)
        self.database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self._connection() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS calendar_sessions (
                    session_id TEXT PRIMARY KEY, origin_id TEXT NOT NULL,
                    email TEXT NOT NULL, challenge_id TEXT,
                    code_digest TEXT, code_expires REAL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    verified_until REAL, state TEXT NOT NULL DEFAULT 'empty'
                );
                CREATE TABLE IF NOT EXISTS calendar_access_events (
                    id INTEGER PRIMARY KEY, email TEXT NOT NULL,
                    origin_id TEXT NOT NULL, session_id TEXT NOT NULL,
                    kind TEXT NOT NULL, created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS access_events_email
                    ON calendar_access_events(email, kind, created_at);
                CREATE INDEX IF NOT EXISTS access_events_origin
                    ON calendar_access_events(origin_id, kind, created_at);
                CREATE INDEX IF NOT EXISTS access_events_session
                    ON calendar_access_events(session_id, kind, created_at);
                """
            )
        self.database.chmod(0o600)

    @contextmanager
    def _connection(self):
        db = sqlite3.connect(self.database, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def _transaction(self):
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise

    def _registration(self, email):
        contact = self.whitelist.lookup(email)
        return contact

    @staticmethod
    def _revoke(db, session_id):
        db.execute(
            "UPDATE calendar_sessions SET code_digest=NULL, verified_until=NULL, "
            "state='empty' WHERE session_id=? AND state!='closed'",
            (session_id,),
        )

    @staticmethod
    def _session(db, session_id):
        return db.execute(
            "SELECT * FROM calendar_sessions WHERE session_id=?", (session_id,)
        ).fetchone()

    def _digest(self, session_id, email, challenge_id, code):
        message = json.dumps([session_id, email, challenge_id, code]).encode()
        return hmac.new(self.secret.encode(), message, hashlib.sha256).hexdigest()

    def _limited(self, db, session, kind, window, email_limit, origin_limit, now):
        rows = db.execute(
            "SELECT email, origin_id FROM calendar_access_events WHERE kind=? "
            "AND created_at>? AND (email=? OR origin_id=?)",
            (kind, now - window, session["email"], session["origin_id"]),
        ).fetchall()
        return (
            sum(row["email"] == session["email"] for row in rows) >= email_limit
            or sum(row["origin_id"] == session["origin_id"] for row in rows)
            >= origin_limit
        )

    @staticmethod
    def _event(db, session, kind, now):
        db.execute(
            "INSERT INTO calendar_access_events "
            "(email, origin_id, session_id, kind, created_at) VALUES (?, ?, ?, ?, ?)",
            (session["email"], session["origin_id"], session["session_id"], kind, now),
        )

    def start(self, session_id: str, email: str, origin_id: str) -> dict:
        return self._issue(session_id, normalize_email(email), origin_id)

    def resend(self, session_id: str, challenge_id: str) -> dict:
        return self._issue(session_id, previous_challenge=challenge_id)

    def _issue(self, session_id, email=None, origin_id=None, previous_challenge=None):
        now = self.clock()
        policy = self.policy
        with self._transaction() as db:
            session = self._session(db, session_id)
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
            if session and session["origin_id"] != origin_id:
                return {"status": "invalid_session"}
            if not session:
                db.execute(
                    "INSERT INTO calendar_sessions(session_id, origin_id, email) VALUES (?, ?, ?)",
                    (session_id, origin_id, email),
                )
            elif session["email"] != email or session["state"] == "verified":
                # A new identity or new verification request revokes authorization.
                db.execute(
                    "UPDATE calendar_sessions SET email=?, code_digest=NULL, "
                    "verified_until=NULL, state='empty' WHERE session_id=?",
                    (email, session_id),
                )
        lookup_failed = False
        try:
            registration = self._registration(email)
        except WhitelistUnavailable:
            registration, lookup_failed = None, True
        with self._transaction() as db:
            session = self._session(db, session_id)
            if not session or session["state"] == "closed" or session["email"] != email:
                return {"status": "verification_required"}
            if (
                previous_challenge is not None
                and session["challenge_id"] != previous_challenge
            ):
                return {"status": "verification_required"}
            if lookup_failed:
                self._revoke(db, session_id)
                return {"status": "unavailable"}
            if not registration or not registration.enabled:
                self._revoke(db, session_id)
                return {
                    "status": "not_registered" if not registration else "not_enabled",
                    "message": REGISTRATION_MESSAGE,
                }
            now = self.clock()
            # Retain rate-limit counters across challenges, calls and process restarts.
            db.execute(
                "DELETE FROM calendar_access_events WHERE created_at<?", (now - 86400,)
            )
            latest = db.execute(
                "SELECT MAX(created_at) FROM calendar_access_events WHERE kind='send' "
                "AND (email=? OR session_id=?)",
                (email, session_id),
            ).fetchone()[0]
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
            db.execute(
                "UPDATE calendar_sessions SET challenge_id=?, code_digest=?, code_expires=?, "
                "attempts=0, verified_until=NULL, state='sending' WHERE session_id=?",
                (
                    challenge_id,
                    self._digest(session_id, email, challenge_id, code),
                    expires,
                    session_id,
                ),
            )
            self._event(db, session, "send", now)
        # SMTP delivery never holds the database write lock. Pending codes cannot verify.
        try:
            self.mailer.send_code(email, registration.name, code, policy.code_ttl // 60)
        except Exception:
            with self._transaction() as db:
                db.execute(
                    "UPDATE calendar_sessions SET code_digest=NULL, state='empty' "
                    "WHERE session_id=? AND challenge_id=? AND state='sending'",
                    (session_id, challenge_id),
                )
            return {
                "status": "unavailable",
                "message": "No pude enviar el código. Intente de nuevo más tarde.",
            }
        with self._transaction() as db:
            updated = db.execute(
                "UPDATE calendar_sessions SET state='sent' "
                "WHERE session_id=? AND challenge_id=? AND state='sending'",
                (session_id, challenge_id),
            ).rowcount
        if not updated:
            return {"status": "verification_required"}
        return {
            "status": "code_sent",
            "challenge_id": challenge_id,
            "expires_in_seconds": max(0, int(expires - self.clock())),
        }

    def verify(self, session_id: str, challenge_id: str, code: str) -> dict:
        policy = self.policy
        with self._connection() as db:
            snapshot = self._session(db, session_id)
        if not snapshot or snapshot["state"] in {"empty", "sending", "verified"}:
            return {"status": "verification_required"}
        if snapshot["state"] == "closed":
            return {"status": "session_closed"}
        try:
            registration = self._registration(snapshot["email"])
        except WhitelistUnavailable:
            return {"status": "unavailable"}
        with self._transaction() as db:
            now = self.clock()
            session = self._session(db, session_id)
            if (
                not session
                or session["state"] in {"empty", "sending", "verified"}
                or session["email"] != snapshot["email"]
            ):
                return {"status": "verification_required"}
            if session["state"] == "closed":
                return {"status": "session_closed"}
            if not registration or not registration.enabled:
                self._revoke(db, session_id)
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
                db.execute(
                    "UPDATE calendar_sessions SET code_digest=NULL, state='expired' WHERE session_id=?",
                    (session_id,),
                )
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
                db.execute(
                    "UPDATE calendar_sessions SET attempts=?, state=? WHERE session_id=?",
                    (attempts, "locked" if locked else "sent", session_id),
                )
                self._event(db, session, "failure", now)
                return {
                    "status": "attempts_exceeded" if locked else "invalid_code",
                    "attempts_remaining": max(0, policy.max_attempts - attempts),
                }
            until = now + policy.authorization_ttl
            db.execute(
                "UPDATE calendar_sessions SET code_digest=NULL, state='verified', "
                "verified_until=? WHERE session_id=?",
                (until, session_id),
            )
            return {
                "status": "verified",
                "email": session["email"],
                "expires_in_seconds": policy.authorization_ttl,
            }

    def authorize(self, session_id: str, email: str) -> dict:
        with self._connection() as db:
            snapshot = self._session(db, session_id)
        if not snapshot or snapshot["state"] != "verified":
            return {"status": "verification_required"}
        try:
            registration = self._registration(snapshot["email"])
        except WhitelistUnavailable:
            return {"status": "unavailable"}
        with self._transaction() as db:
            session = self._session(db, session_id)
            if (
                not session
                or session["state"] != "verified"
                or session["email"] != snapshot["email"]
            ):
                return {"status": "verification_required"}
            if not registration or not registration.enabled:
                self._revoke(db, session_id)
                return {"status": "not_enabled", "message": REGISTRATION_MESSAGE}
            if session["email"] != normalize_email(email):
                return {"status": "email_mismatch"}
            if session["verified_until"] <= self.clock():
                return {"status": "expired"}
            return {"status": "authorized", "email": session["email"]}

    def close(self, session_id: str) -> dict:
        with self._transaction() as db:
            db.execute(
                "UPDATE calendar_sessions SET code_digest=NULL, verified_until=NULL, "
                "state='closed' WHERE session_id=?",
                (session_id,),
            )
        return {"status": "closed"}
