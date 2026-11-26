from sqlalchemy import text

from app.__main__ import main
from app.core.config import Settings
from app.db.engine import create_sync_engine
from app.worker import EXIT_SCHEMA_NEWER


def test_the_process_refuses_to_start_on_a_newer_schema(migrated: Settings) -> None:
    engine = create_sync_engine(migrated.sync_database_url)
    with engine.begin() as conn:
        conn.execute(text("UPDATE alembic_version SET version_num = '9999'"))
    engine.dispose()

    assert main() == EXIT_SCHEMA_NEWER
