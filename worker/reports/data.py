"""Fetch data from dmais_portal API endpoints (authenticated via Playwright)."""

from worker.logs import get_logger

logger = get_logger(__name__)


async def fetch_json(page, path: str) -> dict:
    """Fetch JSON from an authenticated portal page.

    The page must already be logged in (from screenshots.py login flow).
    """
    result = await page.evaluate(
        """async ([path]) => {
            const r = await fetch(path);
            if (!r.ok) throw new Error('HTTP ' + r.status);
            return await r.json();
        }""",
        [path],
    )
    return result


async def fetch_status_header(page) -> dict:
    """Fetch Último entrante + Último download timestamps."""
    data = await fetch_json(page, "/backlog/api/status-header/")
    logger.info("data.status_header", keys=list(data.keys())[:5])
    return data


async def fetch_group_counts(page) -> dict:
    """Fetch order counts per group (REPARO, ME, ATIVACAO, SERVICOS)."""
    data = await fetch_json(page, "/backlog/api/group-counts/")
    logger.info("data.group_counts", groups=list(data.keys()))
    return data


async def fetch_city_group_counts(page) -> dict:
    """Fetch order counts per city × group."""
    data = await fetch_json(page, "/backlog/api/city-group-counts/")
    logger.info("data.city_group_counts", cities=len(data))
    return data
