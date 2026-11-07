"""One local worker per SQL database, even when several entry points are open."""

import fcntl
import hashlib
import os
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path


class Busy(RuntimeError):
    pass


class LocalWorkerLock:
    def __init__(self, database_url):
        if database_url.startswith("sqlite:///") and not database_url.endswith(
            ":memory:"
        ):
            database = Path(database_url.removeprefix("sqlite:///")).resolve()
            self.path = database.with_name(database.name + ".worker.lock")
        else:
            identity = hashlib.sha256(database_url.encode()).hexdigest()
            self.path = (
                Path(tempfile.gettempdir()) / f"consulting-worker-{identity}.lock"
            )
        self.local = threading.local()
        self.mutex = threading.Lock()

    @contextmanager
    def hold(self):
        if getattr(self.local, "active", False):
            yield
            return
        if not self.mutex.acquire(blocking=False):
            raise Busy("Ya existe un worker local para esta base de datos.")
        file = None
        try:
            file = os.fdopen(os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600), "a+")
            try:
                fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Busy(
                    "Ya existe un worker local para esta base de datos."
                ) from None
            self.local.active = True
            yield
        finally:
            self.local.active = False
            if file:
                file.close()
            self.mutex.release()
