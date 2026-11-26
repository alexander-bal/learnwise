from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.db.engine import create_db_engine, create_sessionmaker
from app.db.migrate import head_revision


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    # Migrations ran in __main__ before the server started (Processing FR-5).
    engine = create_db_engine(get_settings().database_url)
    app.state.sessionmaker = create_sessionmaker(engine)
    app.state.head_revision = head_revision()
    try:
        yield
    finally:
        await engine.dispose()
