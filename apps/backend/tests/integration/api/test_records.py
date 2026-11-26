import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests.integration.conftest import Sim


async def test_the_console_reads_back_a_request_its_calls_sample_and_key(
    client: httpx.AsyncClient, sim: Sim
) -> None:
    sim.fault("5xx")
    await client.post("/process", json={"message": "billing"}, headers={"X-Request-ID": "bad"})
    sim.clear()
    ok = await client.post(
        "/process",
        json={"message": "shipping"},
        headers={"X-Request-ID": "good", "Idempotency-Key": "k"},
    )
    sample_id = ok.json()["sample_id"]

    samples = (await client.get("/samples")).json()
    requests = (await client.get("/requests")).json()
    calls = (await client.get("/llm-calls", params={"request_id": "bad"})).json()
    detail = (await client.get("/requests/good")).json()
    keys = (await client.get("/idempotency-requests")).json()

    assert samples["total"] == 1 and samples["items"][0]["id"] == sample_id
    assert [(r["request_id"], r["status"], r["attempts"]) for r in requests["items"]] == [
        ("good", "success", 1),
        ("bad", "error", 3),
    ]
    assert requests["items"][1]["error_code"] == "provider_unavailable"
    assert calls["total"] == 3 and {c["request_id"] for c in calls["items"]} == {"bad"}
    assert [c["status"] for c in detail["calls"]] == ["success"]
    assert [s["id"] for s in detail["samples"]] == [sample_id]
    assert detail["idempotency"][0]["key"] == "k"
    assert keys["items"][0]["status"] == "completed"
    assert (await client.get("/requests/nope")).status_code == 404


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
