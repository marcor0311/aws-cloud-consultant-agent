"""PostgreSQL checkpoints per business stage; retries resume completed stages."""

from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid5

import psycopg
from app.delivery.models import ArtifactRef
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


class DeliveryConflict(Exception):
    pass


class DeliveryBusy(Exception):
    pass


class PostgresRepository:
    def __init__(self, dsn: str):
        self.dsn = dsn

    def connect(self):
        return psycopg.connect(
            self.dsn,
            autocommit=True,
            row_factory=dict_row,
            connect_timeout=5,
            client_encoding="utf8",
        )

    def initialize(self):
        migration = (
            Path(__file__).resolve().parents[2] / "migrations" / "001_delivery.sql"
        )
        with self.connect() as conn, conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(210022)")
            conn.execute(migration.read_text(encoding="utf-8"))

    @contextmanager
    def locked(self, delivery_id: UUID):
        with self.connect() as conn:
            acquired = conn.execute(
                "SELECT pg_try_advisory_lock(hashtextextended(%s, 0)) AS ok",
                (str(delivery_id),),
            ).fetchone()["ok"]
            if not acquired:
                raise DeliveryBusy(
                    "La entrega ya se está procesando; reintentar con el mismo identificador"
                )
            try:
                yield RunStore(conn, delivery_id)
            finally:
                conn.execute(
                    "SELECT pg_advisory_unlock(hashtextextended(%s, 0))",
                    (str(delivery_id),),
                )

    def get(self, delivery_id):
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM delivery_runs WHERE delivery_id=%s", (delivery_id,)
            ).fetchone()

    def artifact(self, delivery_id, artifact_id):
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM delivery_artifacts WHERE delivery_id=%s AND artifact_id=%s",
                (delivery_id, artifact_id),
            ).fetchone()


class RunStore:
    def __init__(self, conn, delivery_id):
        self.conn, self.delivery_id = conn, delivery_id

    def get(self):
        return self.conn.execute(
            "SELECT * FROM delivery_runs WHERE delivery_id=%s", (self.delivery_id,)
        ).fetchone()

    def create(self, request, request_hash):
        self.conn.execute(
            "INSERT INTO delivery_runs(delivery_id, request_hash, request, status) VALUES (%s,%s,%s,'accepted')",
            (self.delivery_id, request_hash, Jsonb(request)),
        )

    def save_handoff(self, handoff):
        self.conn.execute(
            "UPDATE delivery_runs SET handoff=%s, status='engineering_complete', error=NULL, updated_at=now() WHERE delivery_id=%s",
            (Jsonb(handoff), self.delivery_id),
        )

    def save_report(self, report, timing):
        self.conn.execute(
            "UPDATE delivery_runs SET report=%s, report_timing=%s, status='draft_ready', error=NULL, updated_at=now() WHERE delivery_id=%s",
            (Jsonb(report), Jsonb(timing), self.delivery_id),
        )

    def blocked(self, detail):
        self.conn.execute(
            "UPDATE delivery_runs SET status='blocked', error=%s, updated_at=now() WHERE delivery_id=%s",
            (detail, self.delivery_id),
        )

    def failed(self):
        self.conn.execute(
            "UPDATE delivery_runs SET status='failed', error='La ejecución falló; puede reintentarse con la misma entrada', updated_at=now() WHERE delivery_id=%s",
            (self.delivery_id,),
        )

    def put_artifact(self, filename, media_type, content: bytes):
        artifact_id = uuid5(self.delivery_id, filename)
        digest = sha256(content).hexdigest()
        self.conn.execute(
            "INSERT INTO delivery_artifacts(artifact_id, delivery_id, filename, media_type, sha256, content) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(artifact_id) DO UPDATE SET content=EXCLUDED.content, sha256=EXCLUDED.sha256",
            (artifact_id, self.delivery_id, filename, media_type, digest, content),
        )
        return ArtifactRef(
            artifact_id=artifact_id,
            filename=filename,
            media_type=media_type,
            sha256=digest,
        )
