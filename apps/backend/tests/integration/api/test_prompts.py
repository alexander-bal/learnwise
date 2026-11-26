import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker


async def test_a_fresh_database_lists_the_seeded_prompt_as_active(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/prompts")

    assert response.status_code == 200
    [version] = response.json()
    assert version["id"] == 1
    assert version["parent_id"] is None
    assert version["status"] == "active"
    assert version["change_reason"] == "Initial prompt"
    # The seeded prompt names these intents and not cancellation or account (simulator.md).
    content = version["content"].lower()
    assert all(intent in content for intent in ("billing", "shipping", "technical_issue"))
    assert "cancellation" not in content and "account" not in content
    assert set(version) == {"id", "parent_id", "status", "change_reason", "content", "created_at"}


async def _add_version(session, version_id: int, parent_id: int, reason: str) -> None:
    await session.execute(
        text(
            "INSERT INTO prompt_versions (id, parent_id, content, change_reason) "
            "VALUES (:id, :parent, :content, :reason)"
        ),
        {
            "id": version_id,
            "parent": parent_id,
            "content": f"prompt {version_id}",
            "reason": reason,
        },
    )


async def _add_review(
    session, review_id: str, base: int, candidate: int, status: str, outcome: str | None
) -> None:
    await session.execute(
        text(
            "INSERT INTO reviews (id, request_id, base_prompt_id, candidate_prompt_id, status, "
            "outcome, expires_at, provider, judge_model, processing_model) VALUES "
            "(:id, 'req', :base, :candidate, :status, :outcome, '2099-01-01T00:00:00.000Z', "
            "'simulator', 'fake-judge', 'fake')"
        ),
        {
            "id": review_id,
            "base": base,
            "candidate": candidate,
            "status": status,
            "outcome": outcome,
        },
    )


async def test_statuses_follow_the_active_pointer_and_each_candidates_review(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker
) -> None:
    async with sessionmaker() as session, session.begin():
        # v2 promoted then superseded by v3; v4 rejected; v5 abandoned; v6 still under review.
        await _add_version(session, 2, 1, "add cancellation")
        await _add_review(session, "r2", 1, 2, "completed", "promoted")
        await _add_version(session, 3, 2, "add account")
        await _add_review(session, "r3", 2, 3, "completed", "promoted")
        await _add_version(session, 4, 3, "worse")
        await _add_review(session, "r4", 3, 4, "completed", "rejected")
        await _add_version(session, 5, 3, "unfinished")
        await _add_review(session, "r5", 3, 5, "failed", None)
        await _add_version(session, 6, 3, "in review")
        await _add_review(session, "r6", 3, 6, "running", None)
        await session.execute(text("UPDATE prompt_state SET active_version_id = 3"))

    response = await client.get("/prompts")

    assert response.status_code == 200
    assert [(v["id"], v["parent_id"], v["status"]) for v in response.json()] == [
        (6, 3, "candidate"),
        (5, 3, "abandoned"),
        (4, 3, "rejected"),
        (3, 2, "active"),
        (2, 1, "superseded"),
        (1, None, "superseded"),
    ]


async def test_the_response_carries_the_callers_request_id(client: httpx.AsyncClient) -> None:
    response = await client.get("/prompts", headers={"X-Request-ID": "trace-7"})

    assert response.headers["X-Request-ID"] == "trace-7"


async def test_a_corrupt_prompt_history_is_a_500_without_details(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker
) -> None:
    async with sessionmaker() as session, session.begin():
        await _add_version(session, 2, 1, "orphan with no review")

    response = await client.get("/prompts", headers={"X-Request-ID": "trace-8"})

    assert response.status_code == 500
    assert response.json() == {
        "code": "internal_error",
        "message": "Internal error",
        "retryable": True,
    }
    assert response.headers["X-Request-ID"] == "trace-8"
