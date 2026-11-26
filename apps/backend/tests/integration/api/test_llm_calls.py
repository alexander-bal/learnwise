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


async def _process(client: httpx.AsyncClient, request_id: str) -> None:
    await client.post(
        "/process", json={"message": "shipping"}, headers={"X-Request-ID": request_id}
    )


async def test_requests_pages_walk_the_list_newest_first(
    client: httpx.AsyncClient, sim: Sim
) -> None:
    for request_id in ("a", "b", "c"):
        await _process(client, request_id)

    pages = [
        (await client.get("/requests", params={"limit": 1, "offset": offset})).json()
        for offset in range(3)
    ]

    assert [p["total"] for p in pages] == [3, 3, 3]
    assert [[r["request_id"] for r in p["items"]] for p in pages] == [["c"], ["b"], ["a"]]


async def test_requests_pages_list_a_reused_request_id_once_and_stay_full(
    client: httpx.AsyncClient, sim: Sim
) -> None:
    # Both "dup" calls end at attempt 1, so each request id is one row however often it ran.
    for request_id in ("a", "b", "dup", "dup"):
        await _process(client, request_id)

    first = (await client.get("/requests", params={"limit": 2})).json()
    second = (await client.get("/requests", params={"limit": 2, "offset": 2})).json()

    assert first["total"] == 3
    assert [r["request_id"] for r in first["items"]] == ["dup", "b"]
    assert [r["request_id"] for r in second["items"]] == ["a"]
