"""Snapshot storage and delta calculation via Redis."""

import json

from worker.logs import get_logger
from worker.redis_queue import redis_queue

logger = get_logger(__name__)

_GROUP_KEY = "reports:last_group_counts"
_CITY_KEY = "reports:last_city_counts"
_TTL = 86400  # 24h


async def save_snapshot(group_counts: dict, city_counts: dict) -> None:
    """Save current counts to Redis for next cycle's delta calculation."""
    client = redis_queue._ensure_client()
    pipe = client.pipeline()
    pipe.set(_GROUP_KEY, json.dumps(group_counts), ex=_TTL)
    pipe.set(_CITY_KEY, json.dumps(city_counts), ex=_TTL)
    await pipe.execute()
    logger.info(
        "stats.snapshot_saved", groups=len(group_counts), cities=len(city_counts)
    )


async def get_deltas(group_counts: dict, city_counts: dict) -> dict:
    """Calculate variation vs previous snapshot stored in Redis.

    Returns:
        {
            "groups": {"REPARO": +3, "ME": -1, ...},
            "cities": {"Vitória": {"REPARO": -12}, "Serra": {"REPARO": +15}, ...},
            "has_previous": bool,  # False for first cycle (no baseline)
        }
    """
    client = redis_queue._ensure_client()

    prev_groups_raw = await client.get(_GROUP_KEY)
    prev_cities_raw = await client.get(_CITY_KEY)

    has_previous = bool(prev_groups_raw)

    if not has_previous:
        logger.info("stats.deltas.no_previous")
        return {"groups": {}, "cities": {}, "has_previous": False}

    prev_groups = json.loads(prev_groups_raw)
    prev_cities = json.loads(prev_cities_raw)

    # Group deltas
    group_deltas = {}
    all_groups = set(group_counts) | set(prev_groups)
    for g in all_groups:
        curr = group_counts.get(g, 0)
        prev = prev_groups.get(g, 0)
        delta = curr - prev
        if delta != 0:
            group_deltas[g] = delta

    # City deltas (per group, non-zero only)
    city_deltas = {}
    all_cities = set(city_counts) | set(prev_cities)
    for cidade in all_cities:
        curr_city = city_counts.get(cidade, {})
        prev_city = prev_cities.get(cidade, {})
        all_groups = set(curr_city) | set(prev_city)
        city_deltas[cidade] = {}
        for g in all_groups:
            delta = curr_city.get(g, 0) - prev_city.get(g, 0)
            if delta != 0:
                city_deltas[cidade][g] = delta

    # Remove cities with no deltas
    city_deltas = {c: d for c, d in city_deltas.items() if d}

    logger.info(
        "stats.deltas.calculated",
        group_deltas=len(group_deltas),
        city_deltas=len(city_deltas),
    )
    return {"groups": group_deltas, "cities": city_deltas, "has_previous": True}
