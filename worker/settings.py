from typing import Literal
from urllib.parse import urlparse

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Django API
    DJANGO_API_BASE_URL: str
    DJANGO_API_TOKEN: str

    # EvolutionAPI
    EVOLUTION_API_URL: str = "http://evolution-api:8080"
    EVOLUTION_API_KEY: str
    EVOLUTION_INSTANCE_NAME: str = "dmais"

    # Redis
    REDIS_URL: str = "redis://redis:6379/0"

    # Polling
    POLLING_INTERVAL_SECONDS: int = 60
    MAX_MESSAGES_PER_MINUTE: int = 4

    # Observabilidade
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # Worker HTTP
    WORKER_HTTP_PORT: int = 8000

    @field_validator("DJANGO_API_BASE_URL", "EVOLUTION_API_URL", mode="before")
    @classmethod
    def normalize_http_url(cls, v: str) -> str:
        value = str(v).strip().rstrip("/")
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("must be an absolute http(s) URL")
        return value

    @field_validator("POLLING_INTERVAL_SECONDS", "MAX_MESSAGES_PER_MINUTE", mode="after")
    @classmethod
    def must_be_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("must be positive integer")
        return v

    @field_validator("WORKER_HTTP_PORT", mode="after")
    @classmethod
    def must_be_valid_tcp_port(cls, v: int) -> int:
        if not 1 <= v <= 65535:
            raise ValueError("must be a valid TCP port between 1 and 65535")
        return v


settings = Settings()
