"""What a /process request holds on to while things change under it."""

import asyncio
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import Settings
from app.main import create_app
from tests.integration.conftest import Sim


async def scalar(sessionmaker: async_sessionmaker, sql: str) -> Any:
    async with sessionmaker() as session:
        return await session.scalar(text(sql))


async def wait_for_running_call(sessionmaker: async_sessionmaker) -> None:
    for _ in range(100):
        if await scalar(sessionmaker, "SELECT count(*) FROM llm_calls WHERE status = 'running'"):
            return
        await asyncio.sleep(0.01)
    raise AssertionError("no call started")


async def test_a_request_that_lost_its_lease_stores_nothing_and_answers_409(
    client: httpx.AsyncClient, sim: Sim, sessionmaker: async_sessionmaker
) -> None:
    sim.fault("delay", seconds=0.3)
    pending = asyncio.create_task(
        client.post("/process", json={"message": "billing"}, headers={"Idempotency-Key": "k"})
    )
    await wait_for_running_call(sessionmaker)
    async with sessionmaker() as session, session.begin():
        await session.execute(text("UPDATE idempotency_requests SET owner_token = 'thief'"))

    response = await pending

    assert response.status_code == 409
    assert response.json()["code"] == "request_in_progress"
    assert await scalar(sessionmaker, "SELECT count(*) FROM samples") == 0
    assert await scalar(sessionmaker, "SELECT status FROM llm_calls") == "success"
    assert await scalar(sessionmaker, "SELECT sample_id FROM llm_calls") is None


async def test_a_request_keeps_the_prompt_it_started_with(
    client: httpx.AsyncClient, sim: Sim, sessionmaker: async_sessionmaker
) -> None:
    sim.fault("delay", seconds=0.3)
    pending = asyncio.create_task(client.post("/process", json={"message": "billing"}))
    await wait_for_running_call(sessionmaker)
    async with sessionmaker() as session, session.begin():
        await session.execute(
            text(
                "INSERT INTO prompt_versions (id, parent_id, content, change_reason) "
                "VALUES (2, 1, 'nothing named', 'test')"
            )
        )
        await session.execute(text("UPDATE prompt_state SET active_version_id = 2"))

    response = await pending

    assert response.json()["prompt_version"] == 1
    assert response.json()["record"]["intent"] == "billing"  # v1 names billing; v2 does not
    assert await scalar(sessionmaker, "SELECT prompt_version_id FROM samples") == 1


@pytest.fixture
def ollama_is_the_simulator(sim: Sim, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the ollama profile at the simulator, so switching to it can be observed."""
    monkeypatch.setenv("OLLAMA_BASE_URL", sim.url)
    monkeypatch.setenv("OLLAMA_PROCESSING_MODEL", "fake-judge")
    monkeypatch.setenv("KEEP_MODEL_WARM", "true")


async def test_a_request_keeps_its_provider_and_a_switch_warms_the_model(
    ollama_is_the_simulator: None,
    client: httpx.AsyncClient,
    sim: Sim,
    sessionmaker: async_sessionmaker,
) -> None:
    sim.fault("delay", seconds=0.3)
    pending = asyncio.create_task(client.post("/process", json={"message": "billing"}))
    await wait_for_running_call(sessionmaker)
    await client.put("/_provider", json={"provider": "ollama"})

    await pending
    for _ in range(100):
        state = (await client.get("/_provider")).json()
        if state["warm_up"] in ("loaded", "failed"):
            break
        await asyncio.sleep(0.02)
    after = await client.post("/process", json={"message": "billing"})

    assert state["warm_up"] == "loaded"
    providers = (await client.get("/samples")).json()["items"]
    assert sorted((s["provider"], s["model"]) for s in providers) == [
        ("ollama", "fake-judge"),
        ("simulator", "fake"),
    ]
    assert after.status_code == 200
    # The warm-up is not a model call: only the two /process calls are logged.
    assert await scalar(sessionmaker, "SELECT count(*) FROM llm_calls") == 2


@pytest.fixture
def ollama_model_missing(sim: Sim, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_BASE_URL", sim.url)
    monkeypatch.setenv("OLLAMA_PROCESSING_MODEL", "not-installed")
    monkeypatch.setenv("KEEP_MODEL_WARM", "true")


async def test_a_failed_warm_up_is_only_logged(
    ollama_model_missing: None, client: httpx.AsyncClient
) -> None:
    switched = await client.put("/_provider", json={"provider": "ollama"})
    for _ in range(100):
        state = (await client.get("/_provider")).json()
        if state["warm_up"] in ("loaded", "failed"):
            break
        await asyncio.sleep(0.02)

    assert switched.status_code == 200
    assert state["warm_up"] == "failed"
    assert state["current"] == "ollama"


async def test_the_api_sweeps_at_startup(
    migrated: Settings, sessionmaker: async_sessionmaker
) -> None:
    async with sessionmaker() as session, session.begin():
        await session.execute(
            text(
                "INSERT INTO llm_calls (id, request_id, operation, provider, model, status, "
                "created_at) VALUES ('left', 'r', 'process', 'simulator', 'fake', 'running', "
                "'2000-01-01T00:00:00.000Z')"
            )
        )

    app = create_app()
    async with app.router.lifespan_context(app):
        for _ in range(100):
            if await scalar(sessionmaker, "SELECT error_code FROM llm_calls") == "interrupted":
                break
            await asyncio.sleep(0.01)

    assert await scalar(sessionmaker, "SELECT status FROM llm_calls") == "error"
    assert await scalar(sessionmaker, "SELECT error_code FROM llm_calls") == "interrupted"
