from sqlalchemy import ForeignKey, Index, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, one_of, timestamp

OPERATIONS = ("process", "judge", "improve_prompt", "evaluate_candidate")


class LlmCall(Base):
    """One row per attempt of a model call (Processing NFR-4)."""

    __tablename__ = "llm_calls"
    __table_args__ = (
        one_of("operation", OPERATIONS),
        one_of("status", ("running", "success", "error", "timeout")),
        Index(None, "request_id"),
        Index(None, "review_id"),
        Index(None, "created_at"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    request_id: Mapped[str] = mapped_column(Text)
    sample_id: Mapped[str | None] = mapped_column(ForeignKey("samples.id"))
    review_id: Mapped[str | None] = mapped_column(ForeignKey("reviews.id"))
    prompt_version_id: Mapped[int | None] = mapped_column(ForeignKey("prompt_versions.id"))
    operation: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)
    provider_request_id: Mapped[str | None] = mapped_column(Text)
    attempt: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    status: Mapped[str] = mapped_column(Text)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = timestamp(default_now=True)
    completed_at: Mapped[str | None] = timestamp(required=False)
