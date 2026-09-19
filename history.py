"""Price observations across cycles, so the panel can answer "is this actually cheap?".

One row per (route, departure date) per day — the day's lowest price — kept in the same sqlite file as the
dedup cache — which the workflow already persists via actions/cache. If that cache is
ever lost the history simply starts filling up again; nothing else depends on it.
"""
import logging
import statistics
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

DB_PATH = Path("data/cache.db")

SPARK_POINTS = 14
STATS_DAYS = 60


def deal_key(deal: dict) -> str:
    return f"{deal['origem']}|{deal['destino']}|{deal['data']}"


def _cutoff_iso(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


async def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS price_daily (
                route  TEXT NOT NULL,
                dia    TEXT NOT NULL,
                price  REAL NOT NULL,
                PRIMARY KEY (route, dia)
            ) WITHOUT ROWID
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS closed_dates (
                origem      TEXT NOT NULL,
                destino     TEXT NOT NULL,
                data_voo    TEXT NOT NULL,
                lead_bucket INTEGER NOT NULL,
                min_price   REAL NOT NULL,
                n_obs       INTEGER NOT NULL,
                PRIMARY KEY (origem, destino, data_voo, lead_bucket)
            ) WITHOUT ROWID
        """)
        # One-off migration from the per-cycle table used until Sep 2026.
        async with db.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'price_history'"
        ) as cur:
            legacy = await cur.fetchone() is not None
        if legacy:
            try:
                await db.execute("""
                    INSERT OR IGNORE INTO price_daily (route, dia, price)
                    SELECT route, substr(seen_at, 1, 10), MIN(price)
                    FROM price_history GROUP BY 1, 2
                """)
                await db.execute("DROP TABLE price_history")
            except aiosqlite.Error as e:
                logger.error(f"histórico: migração falhou, tabela antiga mantida: {e}")
        await db.commit()


async def record(deals: list[dict], seen_at: datetime | None = None) -> int:
    """Upsert this cycle's prices; each route+date keeps one row per day, the lowest."""
    dia = (seen_at or datetime.now(timezone.utc)).date().isoformat()
    rows = [
        (deal_key(d), dia, float(d["preco"]))
        for d in deals
        if d.get("preco") is not None and d["preco"] > 0
    ]
    if not rows:
        return 0
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executemany(
            "INSERT INTO price_daily (route, dia, price) VALUES (?, ?, ?) "
            "ON CONFLICT (route, dia) DO UPDATE SET price = MIN(price, excluded.price)",
            rows,
        )
        await db.commit()
    return len(rows)


# Days between the observation and the flight. Anything beyond 180 joins the last bucket.
LEAD_BUCKETS = [(0, 7), (8, 14), (15, 30), (31, 60), (61, 90), (91, 120), (121, 180)]


def lead_bucket(days: int) -> int:
    for i, (_lo, hi) in enumerate(LEAD_BUCKETS):
        if days <= hi:
            return i
    return len(LEAD_BUCKETS) - 1


async def rollup_closed(today: date | None = None) -> int:
    """Summarise every flight that already left into closed_dates and drop its daily
    detail. Returns how many route+date keys were closed."""
    cutoff = (today or datetime.now(timezone.utc).date()).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT route, dia, price FROM price_daily WHERE substr(route, -10) < ?", (cutoff,)
        ) as cur:
            rows = await cur.fetchall()
        if not rows:
            return 0

        summary: dict[tuple, list[float]] = {}
        for route, dia, price in rows:
            origem, destino, data_voo = route.split("|")
            lead = (date.fromisoformat(data_voo) - date.fromisoformat(dia)).days
            summary.setdefault((origem, destino, data_voo, lead_bucket(max(lead, 0))), []).append(price)

        await db.executemany(
            "INSERT OR REPLACE INTO closed_dates VALUES (?, ?, ?, ?, ?, ?)",
            [(*key, min(prices), len(prices)) for key, prices in summary.items()],
        )
        await db.execute("DELETE FROM price_daily WHERE substr(route, -10) < ?", (cutoff,))
        await db.commit()
    return len({key[:3] for key in summary})


async def stats(days: int = STATS_DAYS) -> dict[str, dict]:
    """Per route+date: cheapest and median price seen in the window, plus a sparkline of
    the daily minimum (oldest → newest, at most SPARK_POINTS days)."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT route, dia, price FROM price_daily WHERE dia >= ? ORDER BY route, dia",
            (_cutoff_iso(days)[:10],),
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
