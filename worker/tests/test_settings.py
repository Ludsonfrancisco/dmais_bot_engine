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
