from typing import Any

from pydantic import BaseModel


class SampleOut(BaseModel):
    id: str
    request_id: str
    prompt_version_id: int
    input: str
    output: dict[str, Any]
    provider: str
    model: str
    # The stored model_config column; a pydantic model cannot have a field of that name.
    model_settings: str
    created_at: str
