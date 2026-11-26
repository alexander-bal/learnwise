from pydantic import BaseModel

from app.services.prompts import PromptStatus


class PromptVersionOut(BaseModel):
    id: int
    parent_id: int | None
    status: PromptStatus
    change_reason: str
    content: str
    created_at: str
