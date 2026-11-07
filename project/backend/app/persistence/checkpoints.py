"""Open the existing checkpoint backend without changing its path or thread IDs."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.sqlite import SqliteSaver


@contextmanager
def open_checkpointer(url):
    if url.startswith("postgresql://"):
        with PostgresSaver.from_conn_string(url) as saver:
            saver.setup()
            yield saver
    else:
        path = Path(url)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not path.exists():
            path.touch(mode=0o600)
        connection = sqlite3.connect(path, check_same_thread=False)
        try:
            yield SqliteSaver(connection)
        finally:
            connection.close()
