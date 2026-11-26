from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core.config import Settings, get_settings
from app.db.engine import create_db_engine, create_sessionmaker
from app.db.migrate import migrate
from app.main import create_app


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


@pytest.fixture
def migrated(settings: Settings) -> Settings:
    migrate(settings.sync_database_url, settings.database_path)
    return settings


@pytest.fixture
async def engine(migrated: Settings) -> AsyncIterator[AsyncEngine]:
    engine = create_db_engine(migrated.database_url)
    yield engine
    await engine.dispose()


@pytest.fixture
def sessionmaker(engine: AsyncEngine) -> async_sessionmaker:
    return create_sessionmaker(engine)


@pytest.fixture
async def client(migrated: Settings) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield client
