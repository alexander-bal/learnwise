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


INVALID_REQUEST = {"code": "invalid_request", "message": "Invalid request", "retryable": False}


async def test_an_invalid_switch_is_refused_and_keeps_the_current_provider(
    client: httpx.AsyncClient,
) -> None:
    assert (await client.put("/_provider", json={"provider": "ollama"})).status_code == 200
    refused = [
        await client.put("/_provider", json={"provider": "other"}),
        await client.put("/_provider", json={}),
        await client.put(
            "/_provider", content=b"{not json", headers={"Content-Type": "application/json"}
        ),
    ]

    assert [r.status_code for r in refused] == [422, 422, 422]
    assert all(r.json() == INVALID_REQUEST for r in refused)
    # Not the default, so a refusal that reset the choice would show.
    assert (await client.get("/_provider")).json()["current"] == "ollama"
