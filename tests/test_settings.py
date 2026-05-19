import os
import pytest
from pydantic import ValidationError
from worker.settings import Settings

def test_settings_validation_success():
    # Mock environment variables
    env_vars = {
        "DJANGO_API_BASE_URL": "https://api.example.com",
        "DJANGO_API_TOKEN": "secret-token",
        "EVOLUTION_API_KEY": "evo-key",
    }
    
    # In Pydantic Settings, env vars take precedence or provide missing required fields
    # We can pass them as arguments to the constructor to override/fill
    s = Settings(**env_vars)
    
    assert str(s.DJANGO_API_BASE_URL) == "https://api.example.com/"
    assert s.DJANGO_API_TOKEN == "secret-token"
    assert s.EVOLUTION_API_KEY == "evo-key"
    # Test defaults
    assert s.EVOLUTION_INSTANCE_NAME == "dmais"
    assert str(s.REDIS_URL) == "redis://redis:6379/0"
    assert s.LOG_LEVEL == "INFO"

def test_settings_trailing_slash_removal():
    # Pydantic 2 AnyHttpUrl adds a trailing slash by default when converted to string
    # Our validator tries to remove it but AnyHttpUrl might re-add it if it's just the host.
    env_vars = {
        "DJANGO_API_BASE_URL": "https://api.example.com/",
        "DJANGO_API_TOKEN": "token",
        "EVOLUTION_API_KEY": "key",
    }
    s = Settings(**env_vars)
    assert str(s.DJANGO_API_BASE_URL) == "https://api.example.com/"

def test_settings_trailing_slash_removal_with_path():
    env_vars = {
        "DJANGO_API_BASE_URL": "https://api.example.com/v1/",
        "DJANGO_API_TOKEN": "token",
        "EVOLUTION_API_KEY": "key",
    }
    s = Settings(**env_vars)
    # Check if our validator removed the slash from the path
    assert str(s.DJANGO_API_BASE_URL) == "https://api.example.com/v1"

def test_settings_validation_error_missing_required():
    with pytest.raises(ValidationError):
        Settings() # Missing required fields

def test_settings_validation_error_invalid_url():
    with pytest.raises(ValidationError):
        Settings(
            DJANGO_API_BASE_URL="not-a-url",
            DJANGO_API_TOKEN="token",
            EVOLUTION_API_KEY="key"
        )

def test_settings_validation_error_invalid_log_level():
    with pytest.raises(ValidationError):
        Settings(
            DJANGO_API_BASE_URL="https://api.com",
            DJANGO_API_TOKEN="token",
            EVOLUTION_API_KEY="key",
            LOG_LEVEL="INVALID"
        )

def test_settings_validation_error_invalid_port():
    with pytest.raises(ValidationError):
        Settings(
            DJANGO_API_BASE_URL="https://api.com",
            DJANGO_API_TOKEN="token",
            EVOLUTION_API_KEY="key",
            WORKER_HTTP_PORT=70000
        )

if __name__ == "__main__":
    # Simple manual run if pytest is not available or for quick check
    try:
        s = Settings(
            DJANGO_API_BASE_URL="https://api.dmais.com.br",
            DJANGO_API_TOKEN="test_token",
            EVOLUTION_API_KEY="test_key"
        )
        print("Settings validation passed!")
        print(f"Base URL: {s.DJANGO_API_BASE_URL}")
    except ValidationError as e:
        print(f"Settings validation failed: {e}")
