"""Automatic report scheduler — morning message + bi-hourly cycles."""

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from worker.logs import get_logger
from worker.reports.formatter import format_cycle_report, format_morning_message
from worker.reports.stats import get_deltas, save_snapshot
from worker.reports.data import (
    fetch_city_group_counts,
    fetch_group_counts,
    fetch_status_header,
)
from worker.reports.screenshots import capture_portal_page
from worker.settings import settings

logger = get_logger(__name__)

# America/Sao_Paulo timezone
_TZ = ZoneInfo(settings.REPORT_TIMEZONE)

# Schedule
_MORNING_HOUR = 6
_MORNING_MINUTE = 0
_FIRST_CYCLE_HOUR = 6
_FIRST_CYCLE_MINUTE = 10
_INTERVAL_HOURS = 2
_LAST_CYCLE_HOUR = 20
_LAST_CYCLE_MINUTE = 10

# Prevent duplicate sends
_sent_morning_today: str | None = None
_sent_cycles: set[str] = set()

# Print definitions
_PRINTS = [
    {
        "path": "/backlog/",
        "vw": 1920,
        "vh": 1170,
        "el": "#matrix-inner",
        "row": "cidade",
        "col": "grupo",
        "cap": "*BACKLOG DMAIS (Todas as Cidades)*",
    },
    {
        "path": "/backlog/",
        "vw": 1920,
        "vh": 720,
        "el": "#matrix-inner",
        "row": "cidade_grupo",
        "col": None,
        "cap": "*BACKLOG DMAIS (Área Dmais)*",
    },
    {
        "path": "/backlog/",
        "vw": 1920,
        "vh": 720,
        "el": "#abortados-inner",
        "row": None,
        "col": None,
        "cap": "*REPAROS ABORTADOS*",
        "light": True,
    },
]


def _now() -> datetime:
    return datetime.now(_TZ)


def _today_str() -> str:
    return _now().strftime("%Y-%m-%d")


async def _send_morning(ctx_page) -> None:
    """Send the morning greeting message."""
    logger.info("scheduler.morning")
    text = format_morning_message()

    from worker.evolution_client import evolution_client
    from worker.reports.destinations import get_report_destinations

    for dest in get_report_destinations():
        await evolution_client.send_group_text_message(dest.group_jid, text)

    global _sent_morning_today
    _sent_morning_today = _today_str()


async def _send_cycle(hour_label: str, ctx_browser) -> None:
    """Capture prints, fetch data, and send the full cycle report."""
    logger.info("scheduler.cycle", hour=hour_label)

    from playwright.async_api import async_playwright

    from worker.evolution_client import evolution_client
    from worker.reports.destinations import get_report_destinations

    destinations = get_report_destinations()

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        ctx = await browser.new_context(viewport={"width": 1920, "height": 720})
        page = await ctx.new_page()

        # Login
        await page.goto(f"{settings.DMAIS_PORTAL_URL}/login/", wait_until="networkidle")
        await page.fill('input[type="email"]', settings.DMAIS_PORTAL_EMAIL)
        await page.fill('input[type="password"]', settings.DMAIS_PORTAL_PASSWORD)
        await page.click('button[type="submit"]')
        await page.wait_for_url(lambda u: "/login" not in u, timeout=15000)

        # Fetch data
        status = await fetch_status_header(page)
        group_counts = await fetch_group_counts(page)
        city_counts = await fetch_city_group_counts(page)
        deltas = await get_deltas(group_counts, city_counts)
        await save_snapshot(group_counts, city_counts)

        await browser.close()

    # Format text report
    entrante = status.get("ultima_atualizacao_abertura", "--:--")
    download = status.get("ultimo_download", "--:--")
    text = format_cycle_report(
        hour_label,
        entrante,
        download,
        group_counts,
        deltas["groups"],
        deltas["cities"],
        deltas["has_previous"],
    )

    # Send prints
    for prt in _PRINTS:
        img = await capture_portal_page(
            prt["path"],
            viewport_width=prt["vw"],
            viewport_height=prt["vh"],
            element_selector=prt["el"],
            row_dim=prt.get("row"),
            col_dim=prt.get("col"),
            light_mode=prt.get("light", False),
        )
        for dest in destinations:
            await evolution_client.send_group_image_message(
                dest.group_jid, img, caption=prt["cap"]
            )

    # Send text report
    for dest in destinations:
        await evolution_client.send_group_text_message(dest.group_jid, text)

    global _sent_cycles
    _sent_cycles.add(f"{_today_str()}:{hour_label}")


async def run_scheduler() -> None:
    """Main scheduler loop. Runs forever, checking every 60 seconds."""
    logger.info("scheduler.start")

    while True:
        try:
            now = _now()

            # Reset state on new day
            global _sent_morning_today, _sent_cycles
            today = _today_str()
            if _sent_morning_today and _sent_morning_today != today:
                _sent_morning_today = None
                _sent_cycles.clear()

            # Morning message at 06:00
            if (
                now.hour == _MORNING_HOUR
                and now.minute >= _MORNING_MINUTE
                and _sent_morning_today != today
            ):
                await _send_morning(None)
                logger.info("scheduler.morning_sent")

            # Cycle times: 06:10, 08:10, ..., 20:10
            cycle_hour = now.hour
            cycle_minute = now.minute
            cycle_key = f"{today}:{cycle_hour:02d}:{cycle_minute:02d}"

            is_cycle_time = (
                _FIRST_CYCLE_HOUR <= cycle_hour <= _LAST_CYCLE_HOUR
                and cycle_minute >= _FIRST_CYCLE_MINUTE
                and (cycle_hour - _FIRST_CYCLE_HOUR) % _INTERVAL_HOURS == 0
            )

            if is_cycle_time and cycle_key not in _sent_cycles:
                hour_label = f"{cycle_hour:02d}:{cycle_minute:02d}"
                await _send_cycle(hour_label, None)
                logger.info("scheduler.cycle_sent", hour=hour_label)

            await asyncio.sleep(60)

        except Exception as exc:
            logger.error("scheduler.error", error=str(exc))
            await asyncio.sleep(60)
