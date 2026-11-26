"""Migrations (Processing FR-5): one immediate transaction, applied once, all or nothing."""

import sqlite3
import threading
import time
from pathlib import Path

import pytest
from sqlalchemy import text

from app.core.config import Settings
from app.db.engine import create_sync_engine
from app.db.migrate import head_revision, migrate


def tables(path: Path) -> set[str]:
    with sqlite3.connect(path) as db:
        return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def test_processes_starting_together_apply_the_migrations_once(settings: Settings) -> None:
    # A database already in WAL mode, as after the first start: the switch to WAL cannot
    # wait for a lock (see the xfail below), so only the version check is under test here.
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(settings.database_path) as db:
        db.execute("PRAGMA journal_mode = WAL").fetchall()
    barrier = threading.Barrier(4)
    errors: list[BaseException] = []

    def run() -> None:
        barrier.wait()
        try:
            migrate(settings.sync_database_url, settings.database_path)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)

    assert errors == []
    with sqlite3.connect(settings.database_path) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchall() == [
            (head_revision(),)
        ]
        # The seed ran once, not once per process.
        assert db.execute("SELECT count(*) FROM prompt_versions").fetchone() == (1,)


def test_migrating_a_database_already_at_head_changes_nothing(migrated: Settings) -> None:
    engine = create_sync_engine(migrated.sync_database_url)
    with engine.begin() as conn:
        conn.execute(text("UPDATE prompt_versions SET change_reason = 'edited by hand'"))
    engine.dispose()

    migrate(migrated.sync_database_url, migrated.database_path)

    with sqlite3.connect(migrated.database_path) as db:
        assert db.execute("SELECT change_reason FROM prompt_versions").fetchall() == [
            ("edited by hand",)
        ]
        assert db.execute("SELECT version_num FROM alembic_version").fetchall() == [
            (head_revision(),)
        ]


def test_a_migration_that_fails_leaves_the_database_as_it_was(settings: Settings) -> None:
    # A database the migrations did not make, with a table of theirs already in it.
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(settings.database_path) as db:
        db.execute("CREATE TABLE samples (id TEXT PRIMARY KEY)")
        db.execute("INSERT INTO samples VALUES ('mine')")
    before = tables(settings.database_path)

    with pytest.raises(Exception, match="samples"):
        migrate(settings.sync_database_url, settings.database_path)

    # All or nothing: no half-applied schema, no version stamped, the data untouched.
    assert tables(settings.database_path) == before == {"samples"}
    with sqlite3.connect(settings.database_path) as db:
        assert db.execute("SELECT id FROM samples").fetchall() == [("mine",)]


@pytest.mark.xfail(
    strict=True,
    reason="BUG: PRAGMA journal_mode = WAL (db/engine.py _apply_pragmas) fails at once with "
    "'database is locked', ignoring busy_timeout, when another process holds the write lock "
    "of a database not yet in WAL mode - so API and worker started together on a fresh "
    "database can crash (~10% of cold starts of 4 processes)",
)
def test_a_process_starting_while_another_holds_a_fresh_database_waits_for_it(
    settings: Settings,
) -> None:
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    holder = sqlite3.connect(settings.database_path, isolation_level=None, check_same_thread=False)
    holder.execute("BEGIN IMMEDIATE")

    def release() -> None:
        holder.execute("ROLLBACK")
        holder.close()

    timer = threading.Timer(0.5, release)
    timer.start()
    try:
        started = time.monotonic()
        migrate(settings.sync_database_url, settings.database_path)  # should wait, then apply
        assert time.monotonic() - started >= 0.4
    finally:
        timer.join()
    assert "alembic_version" in tables(settings.database_path)
