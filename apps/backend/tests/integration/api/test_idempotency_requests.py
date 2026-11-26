import httpx

from tests.integration.conftest import Sim


async def test_idempotency_requests_lists_a_completed_key(
    client: httpx.AsyncClient, sim: Sim
) -> None:
    await client.post("/process", json={"message": "shipping"}, headers={"Idempotency-Key": "k"})

    keys = (await client.get("/idempotency-requests")).json()

    assert keys["total"] == 1
    assert keys["items"][0]["key"] == "k" and keys["items"][0]["status"] == "completed"
