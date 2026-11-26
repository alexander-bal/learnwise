"""The LLM call log: one llm_calls row per attempt (Processing NFR-4).

A row is written `running` before its attempt and closed after it, so an attempt in flight
when the process died stays visible. Message text, outputs and prompts never go in it.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.time import now_iso
from app.models import LlmCall


@dataclass(frozen=True)
class CallContext:
    operation: str
    request_id: str
    prompt_version_id: int | None = None
    review_id: str | None = None


def new_call(ctx: CallContext, *, provider: str, model: str, attempt: int) -> LlmCall:
    return LlmCall(
        id=uuid.uuid4().hex,
        request_id=ctx.request_id,
        review_id=ctx.review_id,
        prompt_version_id=ctx.prompt_version_id,
        operation=ctx.operation,
        provider=provider,
        model=model,
        attempt=attempt,
        status="running",
        created_at=now_iso(),
    )


async def close_call(
    session: AsyncSession,
    call_id: str,
    *,
    status: str,
    duration_ms: int,
    completed_at: str,
    sample_id: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    provider_request_id: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    await session.execute(
        update(LlmCall)
        .where(LlmCall.id == call_id, LlmCall.status == "running")
        .values(
            status=status,
            duration_ms=duration_ms,
            completed_at=completed_at,
            sample_id=sample_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            provider_request_id=provider_request_id,
            error_code=error_code,
            error_message=error_message,
        )
    )
