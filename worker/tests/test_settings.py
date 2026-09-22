import pytest
from pydantic import ValidationError

from worker.settings import Settings


def _base(**overrides) -> dict:
    defaults = {
        "DJANGO_API_BASE_URL": "https://api.example.com",
        "DJANGO_API_TOKEN": "token123",
        "EVOLUTION_API_KEY": "evo-key",
    }
    defaults.update(overrides)
    return defaults


def test_invalid_log_level_raises():
    with pytest.raises(ValidationError):
        Settings(**_base(LOG_LEVEL="VERBOSE"))


def test_polling_interval_zero_raises():
    with pytest.raises(ValidationError):
        Settings(**_base(POLLING_INTERVAL_SECONDS=0))


def test_django_url_trailing_slash_stripped():
    s = Settings(**_base(DJANGO_API_BASE_URL="https://api.example.com/"))
    assert s.DJANGO_API_BASE_URL == "https://api.example.com"


def test_settings_validation_success():
    env_vars = {
        "DJANGO_API_BASE_URL": "https://api.example.com",
        "DJANGO_API_TOKEN": "secret-token",
        "EVOLUTION_API_KEY": "evo-key",
        "EVOLUTION_INSTANCE_NAME": "dmais",
        "REDIS_URL": "redis://redis:6379/0",
    }
    s = Settings(**env_vars)

    assert s.DJANGO_API_BASE_URL == "https://api.example.com"
    assert s.DJANGO_API_TOKEN == "secret-token"
    assert s.EVOLUTION_API_KEY == "evo-key"
    # Test defaults
    assert s.EVOLUTION_INSTANCE_NAME == "dmais"
    assert s.REDIS_URL == "redis://redis:6379/0"
    assert s.MAX_MESSAGES_PER_MINUTE == 4
    assert s.LOG_LEVEL == "INFO"


def test_settings_trailing_slash_removal_with_path():
    env_vars = {
        "DJANGO_API_BASE_URL": "https://api.example.com/v1/",
        "DJANGO_API_TOKEN": "token",
        "EVOLUTION_API_KEY": "key",
    }
    s = Settings(**env_vars)
    assert str(s.DJANGO_API_BASE_URL) == "https://api.example.com/v1"


def test_settings_validation_error_missing_required(monkeypatch):
    monkeypatch.delenv("DJANGO_API_BASE_URL", raising=False)
    monkeypatch.delenv("DJANGO_API_TOKEN", raising=False)
    monkeypatch.delenv("EVOLUTION_API_KEY", raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # Missing required fields


def test_settings_validation_error_invalid_url():
    with pytest.raises(ValidationError):
        Settings(
            DJANGO_API_BASE_URL="not-a-url",
            DJANGO_API_TOKEN="token",
            EVOLUTION_API_KEY="key",
        )


def test_settings_validation_error_invalid_port():
    with pytest.raises(ValidationError):
        Settings(
            DJANGO_API_BASE_URL="https://api.com",
            DJANGO_API_TOKEN="token",
            EVOLUTION_API_KEY="key",
            WORKER_HTTP_PORT=70000,
        )


def test_settings_validation_error_evolution_url_without_protocol():
    with pytest.raises(ValidationError):
        Settings(
            DJANGO_API_BASE_URL="https://api.com",
            DJANGO_API_TOKEN="token",
            EVOLUTION_API_KEY="key",
            EVOLUTION_API_URL="evolution-api:8080",
        )
