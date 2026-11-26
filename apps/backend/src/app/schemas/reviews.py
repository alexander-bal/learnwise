from typing import Any

from pydantic import BaseModel

from app.schemas.llm_calls import LlmCallOut


class ReviewStartOut(BaseModel):
    review_id: str
    status: str


class ReviewInProgressOut(BaseModel):
    code: str
    message: str
    retryable: bool
    review_id: str


class ReviewOut(BaseModel):
    id: str
    request_id: str
    status: str
    outcome: str | None
    base_prompt_id: int
    candidate_prompt_id: int | None
    attempts: int
    next_attempt_at: str | None
    lease_expires_at: str | None
    expires_at: str
    provider: str
    judge_model: str
    processing_model: str
    evaluation_config: dict[str, Any]
    error_code: str | None
    error_message: str | None
    created_at: str
    started_at: str | None
    completed_at: str | None
    samples: int
    base_score: int | None
    candidate_score: int | None
    left_out: int


class JudgedOutputOut(BaseModel):
    output: dict[str, Any] | None
    expected: dict[str, Any] | None
    judged: bool
    unjudgeable: bool
    in_error: bool
    points: int
    explanation: str | None


class JudgmentPairOut(BaseModel):
    sample_id: str
    message: str
    sample_created_at: str
    base: JudgedOutputOut | None
    candidate: JudgedOutputOut | None
    left_out: bool


class ReviewPromptOut(BaseModel):
    id: int
    parent_id: int | None
    content: str
    change_reason: str
    created_at: str
    status: str


class ReviewDetailOut(ReviewOut):
    base_prompt: ReviewPromptOut | None
    candidate_prompt: ReviewPromptOut | None
    judgments: list[JudgmentPairOut]
    calls: list[LlmCallOut]
