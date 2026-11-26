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


def create_db_engine(url: str) -> AsyncEngine:
    engine = create_async_engine(url)

    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_connection: Any, _record: Any) -> None:
        _apply_pragmas(dbapi_connection)

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
