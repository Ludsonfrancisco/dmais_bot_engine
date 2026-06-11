from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from worker.reports.screenshots import capture_portal_page
from worker.settings import Settings


def _settings(**overrides) -> Settings:
    data = {
        "DJANGO_API_BASE_URL": "https://api.example.com",
        "DJANGO_API_TOKEN": "token",
        "EVOLUTION_API_KEY": "evo-key",
    }
    data.update(overrides)
    return Settings(**data)


@pytest.mark.asyncio
async def test_capture_portal_page_requires_url(monkeypatch):
    config = _settings()
    monkeypatch.setattr(config, "DMAIS_PORTAL_URL", "")
    with pytest.raises(ValueError, match="DMAIS_PORTAL_URL"):
        await capture_portal_page("/backlog/", config=config)


@pytest.mark.asyncio
async def test_capture_portal_page_requires_credentials(monkeypatch):
    config = _settings(
        DMAIS_PORTAL_URL="http://localhost:8001", DMAIS_PORTAL_EMAIL="user@example.com"
    )
    monkeypatch.setattr(config, "DMAIS_PORTAL_EMAIL", "")
    with pytest.raises(ValueError, match="DMAIS_PORTAL_EMAIL"):
        await capture_portal_page("/backlog/", config=config)


@pytest.mark.asyncio
async def test_capture_portal_page_returns_bytes():
    config = _settings(
        DMAIS_PORTAL_URL="http://localhost:8001",
        DMAIS_PORTAL_EMAIL="test@example.com",
        DMAIS_PORTAL_PASSWORD="***",
    )

    mock_browser = MagicMock()
    mock_browser.close = AsyncMock()
    mock_context = MagicMock()
    mock_page = AsyncMock()
    mock_page.screenshot = AsyncMock(return_value=b"\x89PNGfake")
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_playwright = MagicMock()
    mock_playwright.chromium.launch = AsyncMock(return_value=mock_browser)

    with patch(
        "worker.reports.screenshots.async_playwright",
        return_value=MagicMock(__aenter__=AsyncMock(return_value=mock_playwright)),
    ):
        result = await capture_portal_page(
            "/backlog/", config=config, viewport_width=1024, viewport_height=600
        )

    assert isinstance(result, bytes)
    assert result == b"\x89PNGfake"

    # Verify login flow was attempted
    mock_page.goto.assert_any_call(
        "http://localhost:8001/login/", wait_until="networkidle"
    )
    mock_page.fill.assert_any_call('input[type="email"]', "test@example.com")
    mock_page.fill.assert_any_call('input[type="password"]', "***")
    mock_page.click.assert_called_with('button[type="submit"]')

    # Verify target page was captured
    mock_page.goto.assert_any_call(
        "http://localhost:8001/backlog/", wait_until="networkidle"
    )
    mock_page.screenshot.assert_called_once_with(full_page=False, type="png")
