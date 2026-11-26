"""Read model for the console: the LLM call log and the /process requests it records."""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import IdempotencyRequest, LlmCall, Sample
from app.services.idempotency_requests import idempotency_dict
from app.services.samples import sample_dict


def call_dict(c: LlmCall) -> dict[str, Any]:
    return {
        "id": c.id,
        "request_id": c.request_id,
        "sample_id": c.sample_id,
        "review_id": c.review_id,
        "prompt_version_id": c.prompt_version_id,
        "operation": c.operation,
        "provider": c.provider,
        "model": c.model,
        "provider_request_id": c.provider_request_id,
        "attempt": c.attempt,
        "status": c.status,
        "input_tokens": c.input_tokens,
        "output_tokens": c.output_tokens,
        "duration_ms": c.duration_ms,
        "error_code": c.error_code,
        "error_message": c.error_message,
        "created_at": c.created_at,
        "completed_at": c.completed_at,
    }


async def list_calls(
    session: AsyncSession,
    *,
    limit: int,
    offset: int,
    request_id: str | None = None,
    status: str | None = None,
    operation: str | None = None,
) -> dict[str, Any]:
    filters = []
    if request_id:
        filters.append(LlmCall.request_id == request_id)
    if status:
        filters.append(LlmCall.status == status)
    if operation:
        filters.append(LlmCall.operation == operation)
    total = await session.scalar(select(func.count()).select_from(LlmCall).where(*filters))
    rows = await session.scalars(
        select(LlmCall)
        .where(*filters)
        .order_by(LlmCall.created_at.desc(), LlmCall.attempt.desc())
        .limit(limit)
        .offset(offset)
    )
    return {"total": total or 0, "items": [call_dict(c) for c in rows]}


async def list_requests(session: AsyncSession, *, limit: int, offset: int) -> dict[str, Any]:
    """`/process` requests that reached the model, one row per request id."""
    latest = (
        select(
            LlmCall.request_id,
            func.min(LlmCall.created_at).label("started_at"),
            func.max(func.coalesce(LlmCall.completed_at, LlmCall.created_at)).label("ended_at"),
            func.count().label("attempts"),
            func.sum(LlmCall.duration_ms).label("total_duration_ms"),
            func.max(LlmCall.sample_id).label("sample_id"),
            func.min(LlmCall.provider).label("provider"),
            func.min(LlmCall.model).label("model"),
            func.min(LlmCall.prompt_version_id).label("prompt_version_id"),
        )
        .where(LlmCall.operation == "process")
        .group_by(LlmCall.request_id)
        .subquery()
    )
    # Exactly one row per request id, so LIMIT and OFFSET count requests. A reused
    # X-Request-ID can leave several calls at the same last attempt number.
    last = (
        select(
            LlmCall.request_id,
            LlmCall.status,
            LlmCall.error_code,
            func.row_number()
            .over(
                partition_by=LlmCall.request_id,
                order_by=(LlmCall.attempt.desc(), LlmCall.created_at.desc(), LlmCall.id.desc()),
            )
            .label("rank"),
        )
        .where(LlmCall.operation == "process")
        .subquery()
    )
    total = await session.scalar(select(func.count()).select_from(latest))
    rows = (
        await session.execute(
            select(latest, last.c.status, last.c.error_code)
            .join(last, (last.c.request_id == latest.c.request_id) & (last.c.rank == 1))
            .order_by(latest.c.started_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    items = [
        {
            "request_id": row.request_id,
            "started_at": row.started_at,
            "ended_at": row.ended_at,
            "attempts": row.attempts,
            "total_duration_ms": row.total_duration_ms,
            "sample_id": row.sample_id,
            "provider": row.provider,
            "model": row.model,
            "prompt_version_id": row.prompt_version_id,
            "status": row.status,
            "error_code": row.error_code,
        }
        for row in rows
    ]
    return {"total": total or 0, "items": items}


async def request_detail(session: AsyncSession, request_id: str) -> dict[str, Any] | None:
    calls = list(
        await session.scalars(
            select(LlmCall)
            .where(LlmCall.request_id == request_id)
            .order_by(LlmCall.created_at, LlmCall.attempt)
        )
    )
    samples = list(await session.scalars(select(Sample).where(Sample.request_id == request_id)))
    if not calls and not samples:
        return None
    sample_ids = [s.id for s in samples]
    records = (
        list(
            await session.scalars(
                select(IdempotencyRequest).where(IdempotencyRequest.sample_id.in_(sample_ids))
            )
        )
        if sample_ids
        else []
    )
    return {
        "request_id": request_id,
        "calls": [call_dict(c) for c in calls],
        "samples": [sample_dict(s) for s in samples],
        "idempotency": [idempotency_dict(r) for r in records],
    }
