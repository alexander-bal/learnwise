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


async def _chat(client: httpx.AsyncClient, model: str = "fake") -> httpx.Response:
    return await client.post(
        "/api/chat",
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": "billing or other"},
                {"role": "user", "content": "billing please"},
            ],
        },
    )


async def test_it_answers_a_chat_like_ollama_and_404s_an_unknown_model(sim) -> None:  # noqa: ANN001
    async with httpx.AsyncClient(base_url=sim.url) as client:
        ok = await _chat(client)
        missing = await _chat(client, "qwen3:0.6b")

    assert ok.status_code == 200
    body = ok.json()
    assert body["done_reason"] == "stop"
    assert body["message"]["content"] == '{"intent": "billing", "urgency": "normal"}'
    assert body["prompt_eval_count"] > 0 and body["eval_count"] > 0
    assert missing.status_code == 404


async def test_the_fault_set_first_wins_and_a_delay_defers_to_the_others(sim) -> None:  # noqa: ANN001
    sim.fault("delay", seconds=0.05)
    sim.fault("reject")
    sim.fault("5xx")
    sim.fault("5xx", model="fake-judge")
    async with httpx.AsyncClient(base_url=sim.url) as client:
        assert (await _chat(client)).status_code == 400
        listed = (await client.get("/_sim/faults")).json()
        await client.delete(f"/_sim/faults/{listed[1]['id']}")
        assert (await _chat(client)).status_code == 500
        assert [f["type"] for f in (await client.get("/_sim/faults")).json()] == [
            "delay",
            "5xx",
            "5xx",
        ]
