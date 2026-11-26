from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, one_of, timestamp

REVIEW_STATUSES = ("pending", "running", "completed", "failed")
OPEN_REVIEW_STATUSES = ("pending", "running")
REVIEW_OUTCOMES = ("promoted", "rejected", "no_changes", "no_proposal", "insufficient_samples")


class Review(Base):
    """A review and its job record (Prompt Improvement Appendix: Schema)."""

    __tablename__ = "reviews"
    __table_args__ = (
        one_of("status", REVIEW_STATUSES),
        one_of("outcome", REVIEW_OUTCOMES, nullable=True),
        CheckConstraint(
            "(status = 'completed') = (outcome IS NOT NULL)", name="outcome_iff_completed"
        ),
        # At most one review is open (Prompt Improvement FR-1).
        Index(
            "uq_reviews_one_open",
            text("(1)"),
            unique=True,
            sqlite_where=text("status IN ('pending', 'running')"),
        ),
        Index(None, "created_at"),
        Index(None, "request_id"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    request_id: Mapped[str] = mapped_column(Text)
    base_prompt_id: Mapped[int] = mapped_column(ForeignKey("prompt_versions.id"))
    candidate_prompt_id: Mapped[int | None] = mapped_column(
        ForeignKey("prompt_versions.id"), unique=True
    )
    status: Mapped[str] = mapped_column(Text, server_default=text("'pending'"))
    outcome: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    next_attempt_at: Mapped[str | None] = timestamp(required=False)
    owner_token: Mapped[str | None] = mapped_column(Text)
    lease_expires_at: Mapped[str | None] = timestamp(required=False)
    expires_at: Mapped[str] = timestamp()
    provider: Mapped[str] = mapped_column(Text)
    judge_model: Mapped[str] = mapped_column(Text)
    processing_model: Mapped[str] = mapped_column(Text)
    evaluation_config: Mapped[str] = mapped_column(Text, server_default=text("'{}'"))
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = timestamp(default_now=True)
    started_at: Mapped[str | None] = timestamp(required=False)
    completed_at: Mapped[str | None] = timestamp(required=False)
