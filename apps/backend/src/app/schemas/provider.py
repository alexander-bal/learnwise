from pydantic import BaseModel

from app.core.config import ProviderName


class ProviderProfileOut(BaseModel):
    name: ProviderName
    base_url: str
    processing_model: str
    judge_model: str


class ProviderOut(BaseModel):
    current: ProviderName
    profiles: list[ProviderProfileOut]
    warm_up: str | None
    breakers: dict[str, str]


class ProviderIn(BaseModel):
    provider: ProviderName
