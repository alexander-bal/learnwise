import httpx

from app.simulator.main import app


async def test_the_simulator_answers_like_ollama_at_its_root() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://sim"
    ) as client:
        root = await client.get("/")
        version = await client.get("/api/version")

    assert root.status_code == 200
    assert root.text == "Ollama is running"
    assert version.json() == {"version": "simulator"}
