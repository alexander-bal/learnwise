import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker


async def test_healthz_answers_ok(client: httpx.AsyncClient) -> None:
    response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readyz_is_ready_on_a_migrated_database(client: httpx.AsyncClient) -> None:
    response = await client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readyz_is_unavailable_when_the_schema_is_not_at_head(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker
) -> None:
    async with sessionmaker() as session, session.begin():
        await session.execute(text("UPDATE alembic_version SET version_num = 'other'"))

    response = await client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}


async def test_readyz_is_unavailable_when_the_database_cannot_be_read(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker
) -> None:
    async with sessionmaker() as session, session.begin():
        await session.execute(text("DROP TABLE alembic_version"))

    response = await client.get("/readyz")
    health = await client.get("/healthz")

    assert response.status_code == 503
    assert health.status_code == 200
