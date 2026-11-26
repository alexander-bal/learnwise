from typing import Literal

from pydantic import BaseModel, ConfigDict

Intent = Literal["billing", "shipping", "technical_issue", "account", "cancellation", "other"]
Urgency = Literal["low", "normal", "high"]


class TriageRecord(BaseModel):
    """Exactly the two fields of a triage record (Processing FR-1)."""

    model_config = ConfigDict(extra="forbid")

    intent: Intent
    urgency: Urgency
