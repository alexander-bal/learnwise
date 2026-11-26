"""A real SQLite write lock, for failures a mock would only imitate."""

import contextlib
import sqlite3
from collections.abc import Generator
from pathlib import Path


@contextlib.contextmanager
def write_lock(database_path: Path) -> Generator[None]:
    """Hold SQLite's write lock, as a stuck writer would.

    Another writer waits `busy_timeout` (5 s, db/engine.py) and then fails with
    "database is locked"; readers are not blocked, as under WAL.
    """
    connection = sqlite3.connect(database_path, isolation_level=None)
    try:
        connection.execute("BEGIN IMMEDIATE")
        yield
    finally:
        with contextlib.suppress(sqlite3.Error):
            connection.execute("ROLLBACK")
        connection.close()
