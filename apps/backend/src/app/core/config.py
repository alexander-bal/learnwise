from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[3]


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

    @property
    def database_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.database_path}"

    @property
    def sync_database_url(self) -> str:
        return f"sqlite:///{self.database_path}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
