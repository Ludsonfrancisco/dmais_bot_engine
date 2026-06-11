"""Authenticated screenshot capture from dmais_portal."""

from playwright.async_api import async_playwright

from worker.logs import get_logger
from worker.settings import Settings, settings

logger = get_logger(__name__)

_LOGIN_TIMEOUT_MS = 15_000
_PAGE_TIMEOUT_MS = 30_000


async def capture_portal_page(
    page_path: str,
    *,
    config: Settings = settings,
    viewport_width: int = 1280,
    viewport_height: int = 720,
) -> bytes:
    """Log into dmais_portal and capture a screenshot of the given page path.

    Args:
        page_path: URL path to capture (e.g. "/backlog/", "/prazo-atendimento/").
        config: Settings instance with portal credentials.
        viewport_width: Browser viewport width in pixels.
        viewport_height: Browser viewport height in pixels.

    Returns:
        PNG image bytes of the captured page.

    Raises:
        ValueError: If portal URL or credentials are missing.
        RuntimeError: If login or page navigation fails.
    """
    if not config.DMAIS_PORTAL_URL:
        raise ValueError("DMAIS_PORTAL_URL is not configured")
    if not config.DMAIS_PORTAL_EMAIL or not config.DMAIS_PORTAL_PASSWORD:
        raise ValueError(
            "DMAIS_PORTAL_EMAIL and DMAIS_PORTAL_PASSWORD are required "
            "for authenticated screenshots"
        )

    base_url = config.DMAIS_PORTAL_URL.rstrip("/")

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(
            viewport={"width": viewport_width, "height": viewport_height},
        )
        page = await context.new_page()

        try:
            # --- Login ---
            logger.info("screenshot.login_start", base_url=base_url)
            await page.goto(f"{base_url}/login/", wait_until="networkidle")

            # Django login form: email field + password + submit button
            await page.fill('input[type="email"]', config.DMAIS_PORTAL_EMAIL)
            await page.fill('input[type="password"]', config.DMAIS_PORTAL_PASSWORD)
            await page.click('button[type="submit"]')

            # Wait for redirect away from /login/
            try:
                await page.wait_for_url(
                    lambda url: "/login" not in url,
                    timeout=_LOGIN_TIMEOUT_MS,
                )
            except Exception:
                raise RuntimeError(
                    "Login failed — still on /login/ page after submit. "
                    "Check DMAIS_PORTAL_EMAIL and DMAIS_PORTAL_PASSWORD."
                )

            logger.info("screenshot.login_ok")

            # --- Navigate to target page ---
            target_url = f"{base_url}{page_path}"
            logger.info("screenshot.capture_start", url=target_url)
            await page.goto(target_url, wait_until="networkidle")

            # Wait for key element to confirm page rendered
            try:
                await page.wait_for_selector(
                    "main, .content, table, .glass-card",
                    timeout=_PAGE_TIMEOUT_MS,
                )
            except Exception:
                pass  # page may have rendered without these selectors

            # Take screenshot
            screenshot = await page.screenshot(full_page=False, type="png")
            logger.info(
                "screenshot.capture_ok",
                path=page_path,
                size_bytes=len(screenshot),
            )
            return screenshot

        finally:
            await browser.close()
