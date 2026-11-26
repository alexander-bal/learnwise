from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def schema_revision(session: AsyncSession) -> str | None:
    return await session.scalar(text("SELECT version_num FROM alembic_version"))
