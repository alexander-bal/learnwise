from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[3]

ProviderName = Literal["simulator", "ollama"]


class ProviderProfile(BaseModel):
    """A model server and the models used on it (Processing NFR-5)."""

    name: ProviderName
    base_url: str
    processing_model: str
    judge_model: str


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_ROOT / ".env", extra="ignore")

    role: Literal["api", "worker"] = "api"
    host: str = "127.0.0.1"
    port: int = 4000
    database_path: Path = BACKEND_ROOT / "var" / "app.db"
    log_level: str = "INFO"
    shutdown_grace_seconds: int = 25
    worker_poll_seconds: float = 1.0
    sim_host: str = "127.0.0.1"
    sim_port: int = 11435

    # Processing FR-1.
    max_message_chars: int = 4000

    # Processing NFR-2.
    request_deadline_seconds: float = 20.0
    attempt_timeout_seconds: float = 8.0
    max_attempts: int = 3
    backoff_base_seconds: float = 0.5
    # Retry-After sent with a 503 when the model server gave none.
    default_retry_after_seconds: float = 1.0

    # Processing FR-3.
    idempotency_lease_seconds: float = 30.0
    idempotency_ttl_hours: float = 24.0

    # Processing NFR-3.
    process_concurrency: int = 2
    breaker_threshold: int = 5
    breaker_open_seconds: float = 15.0

    # Processing FR-5.
    sweep_interval_seconds: float = 60.0

    # Processing NFR-5.
    initial_provider: ProviderName = "simulator"
    ollama_base_url: str = "http://localhost:11434"
    ollama_processing_model: str = "qwen3:0.6b"
    ollama_judge_model: str = "qwen3:8b"
    sim_processing_model: str = "fake"
    sim_judge_model: str = "fake-judge"
    processing_num_ctx: int = 8192
    processing_num_predict: int = 256
    model_seed: int = 42
    keep_model_warm: bool = True

    @property
    def database_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.database_path}"

    @property
    def sync_database_url(self) -> str:
        return f"sqlite:///{self.database_path}"

    def profiles(self) -> dict[ProviderName, ProviderProfile]:
        return {
            "simulator": ProviderProfile(
                name="simulator",
                base_url=f"http://{self.sim_host}:{self.sim_port}",
                processing_model=self.sim_processing_model,
                judge_model=self.sim_judge_model,
            ),
            "ollama": ProviderProfile(
                name="ollama",
                base_url=self.ollama_base_url,
                processing_model=self.ollama_processing_model,
                judge_model=self.ollama_judge_model,
            ),
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
