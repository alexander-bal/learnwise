from pydantic import BaseModel, ConfigDict

from app.llm.schemas import TriageRecord


class ProcessIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Its length is checked against the configured limit (Processing FR-1).
    message: str


class ProcessOut(BaseModel):
    request_id: str
    sample_id: str
    prompt_version: int
    record: TriageRecord


class ErrorOut(BaseModel):
    code: str
    message: str
    retryable: bool
