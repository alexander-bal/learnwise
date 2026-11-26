import asyncio

from sqlalchemy import text

from app.core.config import Settings
from app.db.engine import create_sync_engine
from app.worker import EXIT_SCHEMA_NEWER, run_worker


async def test_the_worker_exits_non_zero_once_the_schema_is_newer_than_its_code(
    migrated: Settings,
) -> None:
    settings = migrated.model_copy(update={"worker_poll_seconds": 0.05})
    worker = asyncio.create_task(run_worker(settings))
    await asyncio.sleep(0.2)
    assert not worker.done()

    engine = create_sync_engine(settings.sync_database_url)
    with engine.begin() as conn:
        conn.execute(text("UPDATE alembic_version SET version_num = '9999'"))
    engine.dispose()

    assert await asyncio.wait_for(worker, timeout=2) == EXIT_SCHEMA_NEWER
