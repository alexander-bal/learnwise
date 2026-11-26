"""Read model for the console: stored samples."""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Sample


def sample_dict(s: Sample, *, with_input: bool = True) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": s.id,
        "request_id": s.request_id,
        "prompt_version_id": s.prompt_version_id,
        "output": s.output,
        "provider": s.provider,
        "model": s.model,
        "model_settings": s.model_config_,
        "created_at": s.created_at,
    }
    if with_input:
        out["input"] = s.input
    return out


async def list_samples(session: AsyncSession, *, limit: int, offset: int) -> dict[str, Any]:
    total = await session.scalar(select(func.count()).select_from(Sample))
    rows = await session.scalars(
        select(Sample).order_by(Sample.created_at.desc(), Sample.id).limit(limit).offset(offset)
    )
    return {"total": total or 0, "items": [sample_dict(s) for s in rows]}
