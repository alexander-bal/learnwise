from fastapi import APIRouter, HTTPException

from app.api.deps import Limit, Offset, SessionDep
from app.schemas.llm_calls import LlmCallOut, RequestDetailOut, RequestSummaryOut
from app.schemas.pagination import Page
from app.services import llm_calls

router = APIRouter(tags=["llm-calls"])


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
        await llm_calls.list_calls(
            session,
            limit=limit,
            offset=offset,
            request_id=request_id,
            status=status,
            operation=operation,
        )
    )


@router.get("/requests")
async def list_requests(
    session: SessionDep, limit: Limit = 50, offset: Offset = 0
) -> Page[RequestSummaryOut]:
    """`/process` requests that reached the model, newest first."""
    return Page[RequestSummaryOut].model_validate(
        await llm_calls.list_requests(session, limit=limit, offset=offset)
    )


@router.get("/requests/{request_id}")
async def get_request(request_id: str, session: SessionDep) -> RequestDetailOut:
    """Everything stored for one request id: its calls, sample and idempotency record."""
    detail = await llm_calls.request_detail(session, request_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Nothing is stored for this request id")
    return RequestDetailOut.model_validate(detail)
