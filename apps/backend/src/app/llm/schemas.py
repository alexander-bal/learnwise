from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, create_model

Intent = Literal["billing", "shipping", "technical_issue", "account", "cancellation", "other"]
Urgency = Literal["low", "normal", "high"]


class TriageRecord(BaseModel):
    """Exactly the two fields of a triage record (Processing FR-1)."""

    model_config = ConfigDict(extra="forbid")

    intent: Intent
    urgency: Urgency


class JudgeVerdict(BaseModel):
    """The judge's verdict on one output (Prompt Improvement FR-2, Judge)."""

    model_config = ConfigDict(extra="forbid")

    record: TriageRecord
    explanation: str = Field(max_length=500)


def proposal_schema(prompt_max_chars: int, reason_max_chars: int) -> type[BaseModel]:
    """The proposal's output schema; it carries both limits (Prompt Improvement FR-2)."""
    return create_model(
        "Proposal",
        __config__=ConfigDict(extra="forbid"),
        prompt=(str, Field(min_length=1, max_length=prompt_max_chars)),
        reason=(str, Field(min_length=1, max_length=reason_max_chars)),
    )
