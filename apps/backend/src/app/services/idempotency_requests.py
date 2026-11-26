"""Read model for the console: idempotency records. The write side is services/idempotency.py."""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import IdempotencyRequest


def idempotency_dict(r: IdempotencyRequest) -> dict[str, Any]:
    return {
        "endpoint": r.endpoint,
        "key": r.key,
        "status": r.status,
        "sample_id": r.sample_id,
        "lease_expires_at": r.lease_expires_at,
        "response_status": r.response_status,
        "response_body": r.response_body,
        "created_at": r.created_at,
        "updated_at": r.updated_at,
    }


async def list_idempotency(session: AsyncSession, *, limit: int, offset: int) -> dict[str, Any]:
    total = await session.scalar(select(func.count()).select_from(IdempotencyRequest))
    rows = await session.scalars(
        select(IdempotencyRequest)
        .order_by(IdempotencyRequest.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return {"total": total or 0, "items": [idempotency_dict(r) for r in rows]}
