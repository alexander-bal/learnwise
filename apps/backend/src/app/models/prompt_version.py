from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, timestamp


class PromptVersion(Base):
    """Every version of the prompt. A row is never changed; its status is derived."""

    __tablename__ = "prompt_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("prompt_versions.id"))
    content: Mapped[str] = mapped_column(Text)
    change_reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = timestamp(default_now=True)
