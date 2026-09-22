from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
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
    POLLING_ENABLED: bool = True
    POLLING_INTERVAL_SECONDS: int = 60
    MAX_MESSAGES_PER_MINUTE: int = 4

    # Webhook (respostas de clientes — coleta de equipamento)
    WEBHOOK_ENABLED: bool = True

    # Conversation timeout (seconds of inactivity before auto-FALHA)
    CONVERSATION_TIMEOUT_SECONDS: int = 14400  # 4 hours

    # Observabilidade
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # Worker HTTP
    WORKER_HTTP_PORT: int = 8000

    # Report Automation (WhatsApp group reports)
    REPORT_TARGETS: str = "test"
    WHATSAPP_TEST_GROUP_JID: str = ""
    WHATSAPP_REPORT_GROUP_JID: str = ""
    REPORT_TIMEZONE: str = "America/Sao_Paulo"

    # Agenda dos relatorios. O scheduler le daqui; mudar horario nao exige
    # mexer no codigo.
    REPORT_SCHEDULER_ENABLED: bool = True
    REPORT_MORNING_TIME: str = "06:00"
    REPORT_CYCLE_FIRST: str = "06:30"
    REPORT_CYCLE_LAST: str = "20:30"
    REPORT_CYCLE_INTERVAL_HOURS: int = 2

    # Legado: nunca foram lidos pelo scheduler, que sempre usou horario fixo
    # no codigo. Ficam aceitos para nao quebrar .env existente.
    REPORTS_ENABLED: bool = False
    REPORT_BACKLOG_CRON: str = "0 8 * * *"
    REPORT_PRAZO_CRON: str = "0 12 * * *"
    REPORT_RESUMO_CRON: str = "0 18 * * *"
    REPORT_SCREENSHOT_CRON: str = ""

    # dmais_portal browser/API access for future screenshots and report data
    DMAIS_PORTAL_URL: str = "http://localhost:8001"
    DMAIS_PORTAL_EMAIL: str = ""
    DMAIS_PORTAL_PASSWORD: str = ""

    @field_validator(
        "DJANGO_API_BASE_URL", "EVOLUTION_API_URL", "DMAIS_PORTAL_URL", mode="before"
    )
    @classmethod
    def normalize_http_url(cls, v: str) -> str:
        value = str(v).strip().rstrip("/")
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("must be an absolute http(s) URL")
        return value

    @field_validator(
        "POLLING_INTERVAL_SECONDS", "MAX_MESSAGES_PER_MINUTE", mode="after"
    )
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

    @field_validator("REPORT_TARGETS", mode="after")
    @classmethod
    def must_be_valid_report_targets(cls, v: str) -> str:
        targets = [part.strip().lower() for part in v.split(",") if part.strip()]
        allowed = {"test", "production"}
        if not targets:
            raise ValueError("must include at least one target: test or production")
        invalid = sorted(set(targets) - allowed)
        if invalid:
            raise ValueError(f"invalid report target(s): {', '.join(invalid)}")
        return ",".join(dict.fromkeys(targets))

    @field_validator(
        "REPORT_MORNING_TIME",
        "REPORT_CYCLE_FIRST",
        "REPORT_CYCLE_LAST",
        mode="after",
    )
    @classmethod
    def must_be_hour_and_minute(cls, v: str) -> str:
        value = v.strip()
        try:
            hour, minute = (int(part) for part in value.split(":"))
        except ValueError:
            raise ValueError("must be HH:MM") from None
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError("must be a valid time between 00:00 and 23:59")
        return f"{hour:02d}:{minute:02d}"

    @field_validator("REPORT_CYCLE_INTERVAL_HOURS", mode="after")
    @classmethod
    def must_be_positive_interval(cls, v: int) -> int:
        if not 1 <= v <= 24:
            raise ValueError("must be between 1 and 24 hours")
        return v

    @field_validator("REPORT_TIMEZONE", mode="after")
    @classmethod
    def must_be_valid_timezone(cls, v: str) -> str:
        value = v.strip()
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("must be a valid IANA timezone") from exc
        return value


settings = Settings()
