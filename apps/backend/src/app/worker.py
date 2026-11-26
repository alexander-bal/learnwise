import asyncio
import contextlib
import logging
import signal

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings
from app.db.engine import create_db_engine, create_sessionmaker
from app.db.migrate import SchemaStatus, classify, script_directory
from app.services.health import schema_revision

log = logging.getLogger(__name__)

EXIT_SCHEMA_NEWER = 3


async def run_worker(settings: Settings) -> int:
    """The review worker loop. Reviews are not implemented yet; it only watches the schema.

    Returns the process exit code: non-zero when the schema moved past this code, so the
    supervisor starts it again on the new code (Processing FR-5).
    """
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    engine = create_db_engine(settings.database_url)
    sessionmaker = create_sessionmaker(engine)
    script = script_directory()
    log.info("worker started")
    try:
        while not stop.is_set():
            try:
                async with sessionmaker() as session:
                    revision = await schema_revision(session)
            except SQLAlchemyError:
                log.warning("worker could not read the schema version", exc_info=True)
            else:
                if classify(revision, script) is SchemaStatus.NEWER:
                    log.error("schema is newer than this code", extra={"revision": revision})
                    return EXIT_SCHEMA_NEWER
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=settings.worker_poll_seconds)
        log.info("worker stopped on signal")
        return 0
    finally:
        await engine.dispose()
