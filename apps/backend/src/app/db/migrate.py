import logging
from enum import StrEnum
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection

from app.db.engine import create_sync_engine

log = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


class SchemaStatus(StrEnum):
    CURRENT = "current"
    BEHIND = "behind"
    NEWER = "newer"


class SchemaNewerThanCode(RuntimeError):
    pass


def alembic_config() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    return cfg


def script_directory() -> ScriptDirectory:
    return ScriptDirectory.from_config(alembic_config())


def head_revision() -> str:
    head = script_directory().get_current_head()
    if head is None:
        raise RuntimeError("no migrations found")
    return head


def classify(current: str | None, script: ScriptDirectory) -> SchemaStatus:
    if current is None:
        return SchemaStatus.BEHIND
    known = {rev.revision for rev in script.walk_revisions()}
    if current not in known:
        return SchemaStatus.NEWER
    return SchemaStatus.CURRENT if current == script.get_current_head() else SchemaStatus.BEHIND


def _current_revision(connection: Connection) -> str | None:
    return MigrationContext.configure(connection).get_current_revision()


def migrate(sync_url: str, database_path: Path) -> None:
    """Apply pending migrations once, under SQLite's write lock (Processing FR-5).

    Raises SchemaNewerThanCode when the database is at a revision this code does not know.
    """
    database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_sync_engine(sync_url)
    script = script_directory()
    try:
        with engine.begin() as connection:  # BEGIN IMMEDIATE
            current = _current_revision(connection)
            status = classify(current, script)
            if status is SchemaStatus.NEWER:
                raise SchemaNewerThanCode(f"database is at unknown revision {current}")
            if status is SchemaStatus.CURRENT:
                log.info("schema up to date", extra={"revision": current})
                return
            cfg = alembic_config()
            cfg.attributes["connection"] = connection
            command.upgrade(cfg, "head")
            log.info("schema migrated", extra={"from_revision": current, "to": head_revision()})
    finally:
        engine.dispose()
