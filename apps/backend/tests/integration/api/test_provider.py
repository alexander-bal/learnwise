import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests.integration.conftest import Sim


async def test_the_provider_switches_between_profiles_and_refuses_an_unknown_one(
    client: httpx.AsyncClient, sim: Sim, sessionmaker: async_sessionmaker
) -> None:
    initial = (await client.get("/_provider")).json()
    assert initial["current"] == "simulator"
    assert {p["name"] for p in initial["profiles"]} == {"simulator", "ollama"}

    switched = await client.put("/_provider", json={"provider": "ollama"})
    assert switched.json()["current"] == "ollama"
    back = await client.put("/_provider", json={"provider": "simulator"})
    assert back.json()["current"] == "simulator"
    assert (await client.put("/_provider", json={"provider": "other"})).status_code == 422
