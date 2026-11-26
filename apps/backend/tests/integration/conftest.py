import socket
import threading
import time
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core.config import Settings, get_settings
from app.db.engine import create_db_engine, create_sessionmaker
from app.db.migrate import migrate
from app.main import create_app
from app.simulator.main import app as simulator_app


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


# Shortened, keeping the ratios of the defaults: the third attempt of a call that never
# answers is cut short by the deadline, as with 20 s and 8 s (Processing NFR-2).
FAST_ENV = {
    "REQUEST_DEADLINE_SECONDS": "1.5",
    "ATTEMPT_TIMEOUT_SECONDS": "0.6",
    "BACKOFF_BASE_SECONDS": "0.02",
    "BREAKER_OPEN_SECONDS": "0.4",
    "IDEMPOTENCY_LEASE_SECONDS": "3",
    "DEFAULT_RETRY_AFTER_SECONDS": "1",
    "SWEEP_INTERVAL_SECONDS": "3600",
    "SHUTDOWN_GRACE_SECONDS": "5",
    "KEEP_MODEL_WARM": "false",
}


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class ThreadServer:
    """A uvicorn server on its own thread and event loop, on a free port."""

    def __init__(self, app: Any) -> None:
        self.port = free_port()
        self.server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=self.port, log_config=None)
        )
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __enter__(self) -> ThreadServer:
        self.thread.start()
        deadline = time.monotonic() + 10
        while not self.server.started:
            if time.monotonic() > deadline or not self.thread.is_alive():
                raise RuntimeError("server did not start")
            time.sleep(0.01)
        return self

    def __exit__(self, *_: object) -> None:
        self.server.should_exit = True
        self.thread.join(10)


class Sim:
    """Sets the simulator's faults through /_sim/faults (docs/simulator.md)."""

    def __init__(self, url: str) -> None:
        self.url = url
        self._http = httpx.Client(base_url=url)

    def fault(self, type: str, **params: Any) -> dict[str, Any]:
        response = self._http.post("/_sim/faults", json={"type": type, **params})
        response.raise_for_status()
        return response.json()

    def clear(self) -> None:
        self._http.delete("/_sim/faults").raise_for_status()


@pytest.fixture(scope="session")
def sim_server() -> Iterator[ThreadServer]:
    with ThreadServer(simulator_app) as server:
        yield server


@pytest.fixture(autouse=True)
def sim(sim_server: ThreadServer, monkeypatch: pytest.MonkeyPatch) -> Iterator[Sim]:
    """Every integration test runs against the simulator, faults cleared, timeouts short."""
    monkeypatch.setenv("SIM_PORT", str(sim_server.port))
    for name, value in FAST_ENV.items():
        monkeypatch.setenv(name, value)
    sim = Sim(sim_server.url)
    sim.clear()
    yield sim
    sim.clear()


@pytest.fixture
def api_server(migrated: Settings) -> Iterator[ThreadServer]:
    """The API on a real socket, for what ASGITransport cannot show: a caller disconnecting."""
    with ThreadServer(create_app()) as server:
        yield server
