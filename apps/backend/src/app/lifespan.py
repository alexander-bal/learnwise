import asyncio
import contextlib
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core import shutdown
from app.core.config import get_settings
from app.core.tasks import TaskTracker
from app.db.engine import create_db_engine, create_sessionmaker
from app.db.migrate import head_revision
from app.llm.gateway import LlmGateway
from app.llm.provider import Providers
from app.services.maintenance import run_sweeper
from app.services.processing import ProcessingService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    # Migrations ran in __main__ before the server started (Processing FR-5).
    settings = get_settings()
    engine = create_db_engine(settings.database_url)
    write_engine = create_db_engine(settings.database_url, immediate=True)
    app.state.sessionmaker = create_sessionmaker(engine)
    app.state.write_sessionmaker = write_sessionmaker = create_sessionmaker(write_engine)
    app.state.head_revision = head_revision()
    app.state.providers = providers = Providers(settings)
    app.state.gateway = gateway = LlmGateway(settings, write_sessionmaker, providers.adapter_for)
    app.state.tasks = tasks = TaskTracker()
    app.state.processing = ProcessingService(
        settings,
        read_sessionmaker=app.state.sessionmaker,
        write_sessionmaker=write_sessionmaker,
        gateway=gateway,
        current_provider=lambda: providers.current,
    )
    if providers.current.name == "ollama" and settings.keep_model_warm:
        providers.start_warm_up()
    sweeper = asyncio.create_task(run_sweeper(settings, write_sessionmaker))
    try:
        yield
    finally:
        sweeper.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sweeper
        # Requests in flight finish within what is left of the grace period (FR-5).
        await tasks.drain(shutdown.remaining(settings.shutdown_grace_seconds))
        await providers.aclose()
        await write_engine.dispose()
        await engine.dispose()
