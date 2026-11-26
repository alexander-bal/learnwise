from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import SessionDep
from app.schemas.records import (
    IdempotencyOut,
    LlmCallOut,
    Page,
    RequestDetailOut,
    RequestSummaryOut,
    SampleOut,
)
from app.services import records

router = APIRouter(tags=["records"])

Limit = Annotated[int, Query(ge=1, le=200)]
Offset = Annotated[int, Query(ge=0)]


@router.get("/samples")
async def list_samples(
    session: SessionDep, limit: Limit = 50, offset: Offset = 0
) -> Page[SampleOut]:
    """Stored samples, newest first."""
    return Page[SampleOut].model_validate(
        await records.list_samples(session, limit=limit, offset=offset)
    )


@router.get("/requests")
async def list_requests(
    session: SessionDep, limit: Limit = 50, offset: Offset = 0
) -> Page[RequestSummaryOut]:
    """`/process` requests that reached the model, newest first."""
    return Page[RequestSummaryOut].model_validate(
        await records.list_requests(session, limit=limit, offset=offset)
    )


@router.get("/requests/{request_id}")
async def get_request(request_id: str, session: SessionDep) -> RequestDetailOut:
    """Everything stored for one request id: its calls, sample and idempotency record."""
    detail = await records.request_detail(session, request_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Nothing is stored for this request id")
    return RequestDetailOut.model_validate(detail)


@router.get("/llm-calls")
async def list_llm_calls(
    session: SessionDep,
    limit: Limit = 100,
    offset: Offset = 0,
    request_id: str | None = None,
    status: str | None = None,
    operation: str | None = None,
) -> Page[LlmCallOut]:
    """The LLM call log, one row per attempt, newest first."""
    return Page[LlmCallOut].model_validate(
        await records.list_calls(
            session,
            limit=limit,
            offset=offset,
            request_id=request_id,
            status=status,
            operation=operation,
        )
    )


@router.get("/idempotency-requests")
async def list_idempotency_requests(
    session: SessionDep, limit: Limit = 50, offset: Offset = 0
) -> Page[IdempotencyOut]:
    """Idempotency records, newest first."""
    return Page[IdempotencyOut].model_validate(
        await records.list_idempotency(session, limit=limit, offset=offset)
    )
