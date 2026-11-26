import asyncio

from app.llm.adapter import ModelSettings, OllamaAdapter
from app.llm.schemas import TriageRecord
from tests.integration.conftest import Sim


async def test_an_attempt_cut_short_closes_its_connection(sim: Sim) -> None:
    """A timed-out attempt must not leave its connection for the next one (Processing NFR-2)."""
    sim.fault("never_answer")
    adapter = OllamaAdapter(sim.url)
    try:
        try:
            async with asyncio.timeout(0.2):
                await adapter.chat(
                    model="fake",
                    prompt="p",
                    content="c",
                    output_schema=TriageRecord,
                    settings=ModelSettings(num_ctx=1, num_predict=1, seed=1),
                )
        except TimeoutError:
            pass
        pool = adapter._client._transport._pool  # ty: ignore[missing-attribute]
        assert pool.connections == []
    finally:
        await adapter.aclose()
