"""SQLite adapter for OTP sessions and counters; preserves existing transactions."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path


class SQLiteVerificationRepository:
    def __init__(self, database):
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self._connection() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS calendar_sessions (
                    session_id TEXT PRIMARY KEY, origin_id TEXT NOT NULL,
                    email TEXT NOT NULL, client_code TEXT, challenge_id TEXT,
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
            # Existing sessions have no client code and must verify again.
            columns = {
                row["name"]
                for row in db.execute("PRAGMA table_info(calendar_sessions)")
            }
            if "client_code" not in columns:
                db.execute("ALTER TABLE calendar_sessions ADD COLUMN client_code TEXT")
                db.execute(
                    "UPDATE calendar_sessions SET code_digest=NULL, verified_until=NULL, state='empty' WHERE state!='closed'"
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
    def transaction(self):
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield _Transaction(db)
                db.commit()
            except Exception:
                db.rollback()
                raise

    def get(self, session_id):
        with self._connection() as db:
            return _Transaction(db).get(session_id)


class _Transaction:
    def __init__(self, connection):
        self._db = connection

    def revoke(self, session_id):
        self._db.execute(
            "UPDATE calendar_sessions SET code_digest=NULL, verified_until=NULL, state='empty' WHERE session_id=? AND state!='closed'",
            (session_id,),
        )

    def get(self, session_id):
        result = self._db.execute(
            "SELECT * FROM calendar_sessions WHERE session_id=?", (session_id,)
        )
        row = result.fetchone()
        return dict(row) if row else None

    def recent_events(self, kind, cutoff, email, origin_id):
        result = self._db.execute(
            "SELECT email, origin_id FROM calendar_access_events WHERE kind=? AND created_at>? AND (email=? OR origin_id=?)",
            (kind, cutoff, email, origin_id),
        )
        return [dict(row) for row in result.fetchall()]

    def record_event(self, email, origin_id, session_id, kind, now):
        self._db.execute(
            "INSERT INTO calendar_access_events (email, origin_id, session_id, kind, created_at) VALUES (?, ?, ?, ?, ?)",
            (email, origin_id, session_id, kind, now),
        )

    def create_session(self, session_id, origin_id, email, client_code):
        self._db.execute(
            "INSERT INTO calendar_sessions(session_id, origin_id, email, client_code) VALUES (?, ?, ?, ?)",
            (session_id, origin_id, email, client_code),
        )

    def change_identity(self, email, client_code, session_id):
        self._db.execute(
            "UPDATE calendar_sessions SET email=?, client_code=?, code_digest=NULL, verified_until=NULL, state='empty' WHERE session_id=?",
            (email, client_code, session_id),
        )

    def prune_events(self, cutoff):
        self._db.execute(
            "DELETE FROM calendar_access_events WHERE created_at<?", (cutoff,)
        )

    def latest_send(self, email, session_id):
        result = self._db.execute(
            "SELECT MAX(created_at) FROM calendar_access_events WHERE kind='send' AND (email=? OR session_id=?)",
            (email, session_id),
        )
        return result.fetchone()[0]

    def save_challenge(self, challenge_id, digest, expires, session_id):
        self._db.execute(
            "UPDATE calendar_sessions SET challenge_id=?, code_digest=?, code_expires=?, attempts=0, verified_until=NULL, state='sending' WHERE session_id=?",
            (challenge_id, digest, expires, session_id),
        )

    def cancel_sending(self, session_id, challenge_id):
        self._db.execute(
            "UPDATE calendar_sessions SET code_digest=NULL, state='empty' WHERE session_id=? AND challenge_id=? AND state='sending'",
            (session_id, challenge_id),
        )

    def confirm_sent(self, session_id, challenge_id):
        result = self._db.execute(
            "UPDATE calendar_sessions SET state='sent' WHERE session_id=? AND challenge_id=? AND state='sending'",
            (session_id, challenge_id),
        )
        return result.rowcount

    def expire(self, session_id):
        self._db.execute(
            "UPDATE calendar_sessions SET code_digest=NULL, state='expired' WHERE session_id=?",
            (session_id,),
        )

    def set_attempts(self, attempts, state, session_id):
        self._db.execute(
            "UPDATE calendar_sessions SET attempts=?, state=? WHERE session_id=?",
            (attempts, state, session_id),
        )

    def mark_verified(self, until, session_id):
        self._db.execute(
            "UPDATE calendar_sessions SET code_digest=NULL, state='verified', verified_until=? WHERE session_id=?",
            (until, session_id),
        )

    def close(self, session_id):
        self._db.execute(
            "UPDATE calendar_sessions SET code_digest=NULL, verified_until=NULL, state='closed' WHERE session_id=?",
            (session_id,),
        )
