from typing import Any

from pydantic import BaseModel

from app.core.config import ProviderName


class SampleOut(BaseModel):
    id: str
    request_id: str
    prompt_version_id: int
    input: str
    output: dict[str, Any]
    provider: str
    model: str
    # The stored model_config column; a pydantic model cannot have a field of that name.
    model_settings: str
    created_at: str


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


class IdempotencyOut(BaseModel):
    endpoint: str
    key: str
    status: str
    sample_id: str | None
    lease_expires_at: str | None
    response_status: int | None
    response_body: dict[str, Any] | None
    created_at: str
    updated_at: str


class RequestDetailOut(BaseModel):
    request_id: str
    calls: list[LlmCallOut]
    samples: list[SampleOut]
    idempotency: list[IdempotencyOut]


class Page[T](BaseModel):
    total: int
    items: list[T]


class ProviderProfileOut(BaseModel):
    name: ProviderName
    base_url: str
    processing_model: str
    judge_model: str


class ProviderOut(BaseModel):
    current: ProviderName
    profiles: list[ProviderProfileOut]
    warm_up: str | None
    breakers: dict[str, str]


class ProviderIn(BaseModel):
    provider: ProviderName
