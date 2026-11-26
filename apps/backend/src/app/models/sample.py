from typing import Any

from sqlalchemy import ForeignKey, Index, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, json_valid, one_of, timestamp


class Sample(Base):
    """A processed message and the validated record returned for it."""

    __tablename__ = "samples"
    __table_args__ = (
        json_valid("output"),
        one_of("provider", ("simulator", "ollama")),
        Index(None, "prompt_version_id", "created_at"),
        Index(None, "created_at"),
        Index(None, "request_id"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    request_id: Mapped[str] = mapped_column(Text)
    prompt_version_id: Mapped[int] = mapped_column(ForeignKey("prompt_versions.id"))
    input: Mapped[str] = mapped_column(Text)
    output: Mapped[dict[str, Any]]
    provider: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)
    model_config_: Mapped[str] = mapped_column("model_config", Text, server_default=text("'{}'"))
    created_at: Mapped[str] = timestamp(default_now=True)
