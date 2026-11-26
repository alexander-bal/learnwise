from typing import Any

from sqlalchemy import ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, json_valid


class ReviewJudgment(Base):
    """One sample's output under one prompt version, and the judge's verdict on it."""

    __tablename__ = "review_judgments"
    __table_args__ = (
        json_valid("output"),
        json_valid("expected_output", nullable=True),
        Index(None, "sample_id"),
    )

    review_id: Mapped[str] = mapped_column(ForeignKey("reviews.id"), primary_key=True)
    sample_id: Mapped[str] = mapped_column(ForeignKey("samples.id"), primary_key=True)
    prompt_version_id: Mapped[int] = mapped_column(
        ForeignKey("prompt_versions.id"), primary_key=True
    )
    output: Mapped[Any]
    # SQL NULL while not judged; JSON null when unjudgeable.
    expected_output: Mapped[Any | None]
    judge_explanation: Mapped[str | None] = mapped_column(Text)
