from sqlalchemy import CheckConstraint, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, timestamp


class PromptState(Base):
    """Exactly one row, with id 1: which prompt version is active."""

    __tablename__ = "prompt_state"
    __table_args__ = (CheckConstraint("id = 1", name="single_row"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    active_version_id: Mapped[int] = mapped_column(ForeignKey("prompt_versions.id"))
    updated_at: Mapped[str] = timestamp(default_now=True)
