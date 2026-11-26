import asyncio
import logging
import sys
from types import FrameType

import uvicorn

from app.core import shutdown
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.migrate import SchemaNewerThanCode, migrate
from app.worker import EXIT_SCHEMA_NEWER, run_worker

log = logging.getLogger("app")


class GracefulServer(uvicorn.Server):
    """Notes when the termination signal came, so shutdown spends one grace period (FR-5)."""

    def handle_exit(self, sig: int, frame: FrameType | None) -> None:
        shutdown.mark_requested()
        super().handle_exit(sig, frame)


def main() -> int:
    settings = get_settings()
    configure_logging(settings.log_level)
    try:
        migrate(settings.sync_database_url, settings.database_path)
    except SchemaNewerThanCode:
        log.exception("refusing to start on a schema newer than this code")
        return EXIT_SCHEMA_NEWER

    if settings.role == "worker":
        return asyncio.run(run_worker(settings))

    config = uvicorn.Config(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        log_config=None,
        timeout_graceful_shutdown=settings.shutdown_grace_seconds,
    )
    GracefulServer(config).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
