from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

PRAGMAS = (
    "PRAGMA journal_mode = WAL",
    "PRAGMA foreign_keys = ON",
    "PRAGMA busy_timeout = 5000",
    "PRAGMA synchronous = FULL",
)


def _apply_pragmas(dbapi_connection: Any) -> None:
    # journal_mode cannot change inside a transaction; a fresh connection has none open.
    cursor = dbapi_connection.cursor()
    try:
        for pragma in PRAGMAS:
            cursor.execute(pragma)
    finally:
        cursor.close()


def create_db_engine(url: str, *, immediate: bool = False) -> AsyncEngine:
    """An async engine; with `immediate`, its transactions take SQLite's write lock up front.

    A deferred transaction that reads and then writes can fail with SQLITE_BUSY under WAL,
    which busy_timeout does not retry, so every write goes through an immediate engine.
    """
    engine = create_async_engine(url)

    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_connection: Any, _record: Any) -> None:
        if immediate:
            dbapi_connection.isolation_level = None  # let SQLAlchemy emit BEGIN itself
        _apply_pragmas(dbapi_connection)

    if immediate:

        @event.listens_for(engine.sync_engine, "begin")
        def _on_begin(connection: Any) -> None:
            connection.exec_driver_sql("BEGIN IMMEDIATE")

    return engine


def create_sync_engine(url: str) -> Engine:
    """A sync engine whose transactions take SQLite's write lock up front.

    pysqlite would otherwise open a deferred transaction, so two processes could both read
    the schema version before either takes the lock.
    """
    engine = create_engine(url)

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection: Any, _record: Any) -> None:
        dbapi_connection.isolation_level = None  # let SQLAlchemy emit BEGIN itself
        _apply_pragmas(dbapi_connection)

    @event.listens_for(engine, "begin")
    def _on_begin(connection: Any) -> None:
        connection.exec_driver_sql("BEGIN IMMEDIATE")

    return engine


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(engine, expire_on_commit=False)
