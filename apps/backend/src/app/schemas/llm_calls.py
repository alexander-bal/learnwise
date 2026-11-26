from pydantic import BaseModel

from app.schemas.idempotency_requests import IdempotencyOut
from app.schemas.samples import SampleOut


class LlmCallOut(BaseModel):
    id: str
    request_id: str
    sample_id: str | None
    review_id: str | None
    prompt_version_id: int | None
    operation: str
    provider: str
    model: str
    provider_request_id: str | None
    attempt: int
    status: str
    input_tokens: int | None
    output_tokens: int | None
    duration_ms: int | None
    error_code: str | None
    error_message: str | None
    created_at: str
    completed_at: str | None


class RequestSummaryOut(BaseModel):
    request_id: str
    started_at: str
    ended_at: str
    attempts: int
    total_duration_ms: int | None
    sample_id: str | None
    provider: str
    model: str
    prompt_version_id: int | None
    status: str
    error_code: str | None


class RequestDetailOut(BaseModel):
    request_id: str
    calls: list[LlmCallOut]
    samples: list[SampleOut]
    idempotency: list[IdempotencyOut]
