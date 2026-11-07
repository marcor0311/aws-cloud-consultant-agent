"""SQLite persistence for pre-registered client companies."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.clients import domain
from app.clients.domain import Client, RegistryUnavailable, normalize_client_code
from app.core.validation import normalize_email


class ClientRepository:
    def __init__(self, database: Path):
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self._connection() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS clients (
                    client_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_code TEXT NOT NULL UNIQUE
                        CHECK(length(client_code)=9 AND
                              client_code GLOB '[A-Z][A-Z][A-Z][A-Z]-[0-9][0-9][0-9][0-9]'),
                    company_name TEXT NOT NULL CHECK(length(trim(company_name)) BETWEEN 1 AND 120),
                    company_email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1))
                )
            """)
        self.database.chmod(0o600)

    @contextmanager
    def _connection(self):
        db = sqlite3.connect(self.database, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _client(row) -> Client | None:
        if row is None:
            return None
        return Client(
            row["client_id"],
            normalize_client_code(row["client_code"]),
            row["company_name"],
            normalize_email(row["company_email"]),
            bool(row["enabled"]),
        )

    def create(self, company_name: str, company_email: str) -> Client:
        name, email = company_name.strip(), normalize_email(company_email)
        if not name or len(name) > 120:
            raise ValueError("La empresa debe tener un nombre de 1 a 120 caracteres.")
        with self._connection() as db:
            # Serialize writers; UNIQUE is the final guard even across processes.
            db.execute("BEGIN IMMEDIATE")
            if db.execute(
                "SELECT 1 FROM clients WHERE company_email=?", (email,)
            ).fetchone():
                raise ValueError("El correo ya está registrado.")
            for _ in range(100):
                code = domain.generate_client_code()
                if db.execute(
                    "SELECT 1 FROM clients WHERE client_code=?", (code,)
                ).fetchone():
                    continue
                try:
                    cursor = db.execute(
                        "INSERT INTO clients(client_code, company_name, company_email) VALUES (?, ?, ?)",
                        (code, name, email),
                    )
                except sqlite3.IntegrityError:
                    if db.execute(
                        "SELECT 1 FROM clients WHERE client_code=?", (code,)
                    ).fetchone():
                        continue
                    raise
                return self._client(
                    db.execute(
                        "SELECT * FROM clients WHERE client_id=?", (cursor.lastrowid,)
                    ).fetchone()
                )
        raise RuntimeError("No se pudo asignar un código único; vuelva a intentarlo.")

    def _lookup(self, column: str, value: str) -> Client | None:
        try:
            with self._connection() as db:
                row = db.execute(
                    f"SELECT * FROM clients WHERE {column}=?", (value,)
                ).fetchone()
                return self._client(row)
        except (sqlite3.Error, OSError, ValueError):
            raise RegistryUnavailable(
                "No se pudo consultar el registro de clientes."
            ) from None

    def lookup_code(self, client_code: str) -> Client | None:
        return self._lookup("client_code", normalize_client_code(client_code))

    def lookup(self, email: str) -> Client | None:
        return self._lookup("company_email", normalize_email(email))
