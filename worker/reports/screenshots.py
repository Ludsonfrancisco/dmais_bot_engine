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
    element_selector: str | None = None,
    select_value: str | None = None,
    row_dim: str | None = None,
    col_dim: str | None = None,
    outlier_group: str | None = None,
    font_scale: float = 1.0,
    light_mode: bool = False,
) -> bytes:
    """Log into dmais_portal and capture a screenshot of the given page path.

    Args:
        page_path: URL path to capture (e.g. "/backlog/", "/prazo-atendimento/").
        config: Settings instance with portal credentials.
        viewport_width: Browser viewport width in pixels.
        viewport_height: Browser viewport height in pixels.
        element_selector: Optional CSS selector. If provided, captures only that
            element instead of the full page.
        select_value: Optional <option> value to select in the first matching
            <select> dropdown after page load.
        row_dim: Option value for the #row-dim <select> (Backlog pivot rows).
        col_dim: Option value for the #col-dim <select> (Backlog pivot columns).

    Returns:
        PNG image bytes of the captured page/element.
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
            await page.fill('input[type="email"]', config.DMAIS_PORTAL_EMAIL)
            await page.fill('input[type="password"]', config.DMAIS_PORTAL_PASSWORD)
            await page.click('button[type="submit"]')
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
            try:
                await page.wait_for_selector(
                    "main, .content, table, .glass-card",
                    timeout=_PAGE_TIMEOUT_MS,
                )
            except Exception:
                pass

            # --- Apply row/col dimension selects via JS (bypass CSS visibility) ---
            # Portal v2 hides these selects with CSS; select_option() fails.
            # JS value + dispatchEvent('change') triggers HTMX re-render.
            for sel_id, dim_value in [("#row-dim", row_dim), ("#col-dim", col_dim)]:
                if not dim_value:
                    continue
                logger.info("screenshot.select_dim", select=sel_id, value=dim_value)
                try:
                    await page.evaluate(
                        f"""() => {{
                            const sel = document.querySelector('{sel_id}');
                            if (sel) {{
                                sel.value = '{dim_value}';
                                sel.dispatchEvent(new Event('change', {{bubbles: true}}));
                            }}
                        }}"""
                    )
                    await page.wait_for_timeout(2500)
                    logger.info(
                        "screenshot.dim_selected", select=sel_id, value=dim_value
                    )
                except Exception as exc:
                    logger.warning(
                        "screenshot.dim_failed",
                        select=sel_id,
                        value=dim_value,
                        error=str(exc),
                    )

            # --- Apply outlier-group select via JS (same hidden-select pattern) ---
            if outlier_group:
                logger.info("screenshot.outlier_group", value=outlier_group)
                try:
                    await page.evaluate(
                        f"""() => {{
                            const sel = document.querySelector('#outlier-group');
                            if (sel) {{
                                sel.value = '{outlier_group}';
                                sel.dispatchEvent(new Event('change', {{bubbles: true}}));
                            }}
                        }}"""
                    )
                    await page.wait_for_timeout(1500)
                    logger.info("screenshot.outlier_selected", value=outlier_group)
                except Exception as exc:
                    logger.warning(
                        "screenshot.outlier_failed",
                        value=outlier_group,
                        error=str(exc),
                    )

            # --- Optional: select a dropdown option by value ---
            if select_value:
                logger.info("screenshot.select_option", value=select_value)
                try:
                    option = await page.query_selector(
                        f'option[value="{select_value}"]'
                    )
                    if option is None:
                        logger.warning(
                            "screenshot.option_not_found", value=select_value
                        )
                    else:
                        select_el = await page.evaluate_handle(
                            """(option) => option.closest('select')""",
                            option,
                        )
                        select_element = select_el.as_element()
                        if select_element is None:
                            logger.warning(
                                "screenshot.select_parent_not_found", value=select_value
                            )
                        else:
                            await select_element.select_option(value=select_value)
                            await page.wait_for_timeout(3000)
                            logger.info(
                                "screenshot.option_selected", value=select_value
                            )
                except Exception as exc:
                    logger.warning(
                        "screenshot.select_failed", value=select_value, error=str(exc)
                    )

            # --- Always hide row-total-badge (may be buggy in some portal versions) ---
            await page.add_style_tag(
                content=".row-total-badge{display:none!important}"
            )
            await page.wait_for_timeout(200)

            # --- Optional: scale up fonts for readability ---
            if font_scale != 1.0:
                logger.info("screenshot.font_scale", scale=font_scale)
                await page.add_style_tag(
                    content=f"body {{ zoom: {font_scale} !important; }}"
                )
                await page.wait_for_timeout(500)

            # --- Optional: switch to light mode via localStorage + reload ---
            if light_mode:
                logger.info("screenshot.light_mode")
                await page.evaluate("localStorage.setItem('theme', 'light')")
                await page.goto(target_url, wait_until="networkidle")
                await page.wait_for_timeout(2000)

            # --- Hide floating UI elements (Insights FAB, mobile nav, loader) ---
            await page.evaluate("""() => {
                const hide_ids = [
                    'ins-fab-root', 'ins-fab', 'ins-panel', 'painel-insights',
                    'painel-chat', 'portal-command-dialog', 'portal-mobile-nav',
                    'mobile-menu', 'mobile-overlay', 'portal-rail', 'portal-pulse',
                    'portal-page-loader',
                ];
                for (const id of hide_ids) {
                    const el = document.getElementById(id);
                    if (el) el.style.display = 'none';
                }
            }""")
            await page.wait_for_timeout(300)

            # Take screenshot
            if element_selector:
                logger.info("screenshot.element_capture", selector=element_selector)
                element = await page.query_selector(element_selector)
                if element is None:
                    raise RuntimeError(f"Element not found: {element_selector}")
                screenshot = await element.screenshot(type="png")
            else:
                screenshot = await page.screenshot(full_page=False, type="png")

            logger.info(
                "screenshot.capture_ok", path=page_path, size_bytes=len(screenshot)
            )
            return screenshot

        finally:
            await browser.close()
