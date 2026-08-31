"""Price observations across cycles, so the panel can answer "is this actually cheap?".

One row per (route, departure date) per cycle, kept in the same sqlite file as the
dedup cache — which the workflow already persists via actions/cache. If that cache is
ever lost the history simply starts filling up again; nothing else depends on it.
"""
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite

DB_PATH = Path("data/cache.db")

SPARK_POINTS = 14
STATS_DAYS = 30
RETENTION_DAYS = 60


def deal_key(deal: dict) -> str:
    return f"{deal['origem']}|{deal['destino']}|{deal['data']}"


def _cutoff_iso(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


async def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS price_history (
                id       INTEGER PRIMARY KEY,
                route    TEXT NOT NULL,
                price    REAL NOT NULL,
                seen_at  TEXT NOT NULL
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_price_history_route ON price_history (route, seen_at)"
        )
        await db.commit()


async def record(deals: list[dict], seen_at: datetime | None = None) -> int:
    """Append this cycle's prices. Deals without a positive price are skipped."""
    ts = (seen_at or datetime.now(timezone.utc)).isoformat()
    rows = [
        (deal_key(d), float(d["preco"]), ts)
        for d in deals
        if d.get("preco") is not None and d["preco"] > 0
    ]
    if not rows:
        return 0
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executemany(
            "INSERT INTO price_history (route, price, seen_at) VALUES (?, ?, ?)", rows
        )
        await db.commit()
    return len(rows)


async def purge_old(days: int = RETENTION_DAYS) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM price_history WHERE seen_at < ?", (_cutoff_iso(days),))
        await db.commit()


async def stats(days: int = STATS_DAYS) -> dict[str, dict]:
    """Per route+date: cheapest and median price seen in the window, plus a sparkline of
    the daily minimum (oldest → newest, at most SPARK_POINTS days)."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """
            SELECT route, substr(seen_at, 1, 10) AS dia, MIN(price)
            FROM price_history
            WHERE seen_at >= ?
            GROUP BY route, dia
            ORDER BY route, dia
            """,
            (_cutoff_iso(days),),
        ) as cursor:
            rows = await cursor.fetchall()

    daily: dict[str, list[float]] = {}
    for route, _dia, price in rows:
        daily.setdefault(route, []).append(price)

    return {
        route: {
            "min": min(prices),
            "med": statistics.median(prices),
            "spark": prices[-SPARK_POINTS:],
        }
        for route, prices in daily.items()
    }
