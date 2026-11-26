from typing import Any

from pydantic import BaseModel


class IdempotencyOut(BaseModel):
    endpoint: str
    key: str
    status: str
    sample_id: str | None
    lease_expires_at: str | None
    response_status: int | None
    response_body: dict[str, Any] | None
    created_at: str
    updated_at: str
