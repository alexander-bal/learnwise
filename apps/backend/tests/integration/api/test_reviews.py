"""POST /reviews and the console's read endpoints (Prompt Improvement FR-1)."""

import json

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests.integration.reviews_helpers import rows, scalar


async def test_starting_a_review_only_writes_a_pending_row_with_what_it_froze(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker
) -> None:
    response = await client.post("/reviews", headers={"X-Request-ID": "start-1"})

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"
    review = (await rows(sessionmaker, "SELECT * FROM reviews"))[0]
    assert review.id == body["review_id"]
    assert (review.status, review.attempts, review.request_id) == ("pending", 0, "start-1")
    assert (review.base_prompt_id, review.provider) == (1, "simulator")
    assert (review.processing_model, review.judge_model) == ("fake", "fake-judge")
    config = json.loads(review.evaluation_config)
    assert config["sample_limit"] == 10
    assert config["processing"]["num_ctx"] == 8192
    assert config["judge"]["num_ctx"] == 16384
    assert review.expires_at > review.created_at
    assert await scalar(sessionmaker, "SELECT count(*) FROM llm_calls") == 0


async def test_a_second_review_is_refused_while_one_is_open(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker
) -> None:
    first = (await client.post("/reviews")).json()["review_id"]

    response = await client.post("/reviews")

    assert response.status_code == 409
    assert response.json() == {
        "code": "review_in_progress",
        "message": "A review is already open",
        "retryable": True,
        "review_id": first,
    }
    assert await scalar(sessionmaker, "SELECT count(*) FROM reviews") == 1


async def test_reviews_are_listed_newest_first_and_read_one_by_one(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker
) -> None:
    first = (await client.post("/reviews")).json()["review_id"]
    async with sessionmaker() as session, session.begin():
        await session.execute(
            text(
                "UPDATE reviews SET status = 'completed', outcome = 'insufficient_samples' "
                "WHERE id = :id"
            ),
            {"id": first},
        )
    second = (await client.post("/reviews")).json()["review_id"]

    page = (await client.get("/reviews")).json()
    assert page["total"] == 2
    assert [r["id"] for r in page["items"]] == [second, first]
    assert page["items"][1]["outcome"] == "insufficient_samples"
    assert page["items"][0]["base_score"] is None

    detail = (await client.get(f"/reviews/{first}")).json()
    assert detail["id"] == first
    assert detail["base_prompt"]["id"] == 1
    assert detail["candidate_prompt"] is None
    assert detail["judgments"] == [] and detail["calls"] == []

    missing = await client.get("/reviews/nope")
    assert missing.status_code == 404
    assert missing.json()["code"] == "not_found"
