import httpx

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

    requests = (await client.get("/requests")).json()
    calls = (await client.get("/llm-calls", params={"request_id": "bad"})).json()
    detail = (await client.get("/requests/good")).json()

    assert [(r["request_id"], r["status"], r["attempts"]) for r in requests["items"]] == [
        ("good", "success", 1),
        ("bad", "error", 3),
    ]
    assert requests["items"][1]["error_code"] == "provider_unavailable"
    assert calls["total"] == 3 and {c["request_id"] for c in calls["items"]} == {"bad"}
    assert [c["status"] for c in detail["calls"]] == ["success"]
    assert [s["id"] for s in detail["samples"]] == [sample_id]
    assert detail["idempotency"][0]["key"] == "k"
    assert (await client.get("/requests/nope")).status_code == 404
