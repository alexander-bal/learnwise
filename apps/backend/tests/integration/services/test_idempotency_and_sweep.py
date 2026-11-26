import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import Settings
from app.db.engine import create_db_engine, create_sessionmaker
from app.services import idempotency
from app.services.idempotency import ClaimOutcome
from app.services.maintenance import sweep_once


async def test_only_one_of_two_concurrent_claims_wins(migrated: Settings) -> None:
    engines = [create_db_engine(migrated.database_url, immediate=True) for _ in range(2)]
    try:

        async def claim(engine) -> ClaimOutcome:  # noqa: ANN001
            async with create_sessionmaker(engine)() as session, session.begin():
                result = await idempotency.claim(
                    session, endpoint="/process", key="race", body_hash="h", lease_seconds=30
                )
            return result.outcome

        outcomes = await asyncio.gather(*(claim(e) for e in engines))
    finally:
        for engine in engines:
            await engine.dispose()

    assert sorted(outcomes) == [ClaimOutcome.CLAIMED, ClaimOutcome.IN_PROGRESS]


async def test_only_the_lease_holder_writes_the_outcome(sessionmaker: async_sessionmaker) -> None:
    async with sessionmaker() as session, session.begin():
        claim = await idempotency.claim(
            session, endpoint="/process", key="k", body_hash="h", lease_seconds=30
        )
        assert claim.owner_token is not None
        assert not await idempotency.finish(
            session, endpoint="/process", key="k", owner_token="someone-else", status="completed"
        )
        assert await idempotency.finish(
            session, endpoint="/process", key="k", owner_token=claim.owner_token, status="failed"
        )


def test_the_hash_ignores_formatting_and_key_order() -> None:
    assert idempotency.request_hash({"b": 1, "a": "é"}) == idempotency.request_hash(
        {"a": "é", "b": 1}
    )
    assert idempotency.request_hash({"a": 1}) != idempotency.request_hash({"a": 2})


async def test_the_sweep_closes_calls_a_dead_process_left_and_removes_old_keys(
    migrated: Settings, sessionmaker: async_sessionmaker
) -> None:
    async with sessionmaker() as session, session.begin():
        for call_id, created in (("old", "2000-01-01T00:00:00.000Z"), ("fresh", None)):
            await session.execute(
                text(
                    "INSERT INTO llm_calls (id, request_id, operation, provider, model, status"
                    + (", created_at" if created else "")
                    + ") VALUES (:id, 'r', 'process', 'simulator', 'fake', 'running'"
                    + (", :created" if created else "")
                    + ")"
                ),
                {"id": call_id, "created": created},
            )
        for key, created in (("stale", "2000-01-01T00:00:00.000Z"), ("recent", None)):
            await session.execute(
                text(
                    "INSERT INTO idempotency_requests (endpoint, key, request_hash, status"
                    + (", created_at" if created else "")
                    + ") VALUES ('/process', :key, 'h', 'completed'"
                    + (", :created" if created else "")
                    + ")"
                ),
                {"key": key, "created": created},
            )

    write = create_db_engine(migrated.database_url, immediate=True)
    try:
        await sweep_once(migrated, create_sessionmaker(write))
    finally:
        await write.dispose()

    async with sessionmaker() as session:
        calls = dict(
            (
                await session.execute(
                    text("SELECT id, status || ':' || coalesce(error_code, '') FROM llm_calls")
                )
            ).all()
        )
        keys = (await session.scalars(text("SELECT key FROM idempotency_requests"))).all()
    assert calls == {"old": "error:interrupted", "fresh": "running:"}
    assert keys == ["recent"]
