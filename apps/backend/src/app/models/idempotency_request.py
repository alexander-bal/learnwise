from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, json_valid, one_of, timestamp


class IdempotencyRequest(Base):
    """One record per idempotency key, scoped to its endpoint (Processing FR-3)."""

    __tablename__ = "idempotency_requests"
    __table_args__ = (
        one_of("status", ("processing", "completed", "retryable_failed", "failed")),
        json_valid("response_body", nullable=True),
        Index(None, "created_at"),
    )

    endpoint: Mapped[str] = mapped_column(Text, primary_key=True)
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    request_hash: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    sample_id: Mapped[str | None] = mapped_column(ForeignKey("samples.id"))
    owner_token: Mapped[str | None] = mapped_column(Text)
    lease_expires_at: Mapped[str | None] = timestamp(required=False)
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[dict[str, Any] | None]
    created_at: Mapped[str] = timestamp(default_now=True)
    updated_at: Mapped[str] = timestamp(default_now=True)
