import httpx

from tests.integration.conftest import Sim


async def test_samples_lists_the_stored_sample(client: httpx.AsyncClient, sim: Sim) -> None:
    ok = await client.post("/process", json={"message": "shipping"})
    sample_id = ok.json()["sample_id"]

    samples = (await client.get("/samples")).json()

    assert samples["total"] == 1 and samples["items"][0]["id"] == sample_id
