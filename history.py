"""Price observations across cycles, so the panel can answer "is this actually cheap?".

One row per (route, departure date) per day — the day's lowest price — kept in the same sqlite file as the
dedup cache — which the workflow already persists via actions/cache. If that cache is
ever lost the history simply starts filling up again; nothing else depends on it.
"""
import logging
import statistics
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

DB_PATH = Path("data/cache.db")

SPARK_POINTS = 14
STATS_DAYS = 60
MIN_ROUTE_DATES = 5     # flight dates a route needs before its median means anything
# Days between the observation and the flight. Anything beyond 180 joins the last bucket.
LEAD_BUCKETS = [(0, 7), (8, 14), (15, 30), (31, 60), (61, 90), (91, 120), (121, 180)]


def deal_key(deal: dict) -> str:
    return f"{deal['origem']}|{deal['destino']}|{deal['data']}"


def _cutoff_date(days: int) -> str:
    """The `dia` column is a plain YYYY-MM-DD, so windows compare against a date, not a timestamp."""
    return (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()


def _split_key(key: str) -> tuple[str, str, str] | None:
    """ORIG|DEST|YYYY-MM-DD -> its three parts, or None when the row is not one of ours.
    Writers only produce well-formed keys, but the database is durable now: one bad row
    must cost a route in a chart, not every future cycle."""
    parts = key.split("|")
    if len(parts) != 3:
        return None
    try:
        date.fromisoformat(parts[2])
    except ValueError:
        return None
    return parts[0], parts[1], parts[2]


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
                med_price   REAL NOT NULL,
                n_obs       INTEGER NOT NULL,
                PRIMARY KEY (origem, destino, data_voo, lead_bucket)
            ) WITHOUT ROWID
        """)
        # med_price landed after the table did. Production had no rows yet, but a dev database
        # might: add the column and seed it with the only estimate that table can offer.
        async with db.execute("PRAGMA table_info(closed_dates)") as cur:
            columns = {row[1] for row in await cur.fetchall()}
        if "med_price" not in columns:
            await db.execute("ALTER TABLE closed_dates ADD COLUMN med_price REAL")
            await db.execute("UPDATE closed_dates SET med_price = min_price")
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
        # A round trip's `preco` is a two-leg total; under the ida leg's key it is not a fare.
        if d.get("tipo") != "roundtrip" and d.get("preco") is not None and d["preco"] > 0
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
        malformed = 0
        for route, dia, price in rows:
            parts = _split_key(route)
            if parts is None:
                malformed += 1      # the DELETE below drops it with the rest of this batch
                continue
            origem, destino, data_voo = parts
            try:
                lead = (date.fromisoformat(data_voo) - date.fromisoformat(dia)).days
            except ValueError:
                malformed += 1
                continue
            summary.setdefault((origem, destino, data_voo, lead_bucket(max(lead, 0))), []).append(price)
        if malformed:
            logger.warning(f"histórico: {malformed} linha(s) de price_daily com chave inválida descartadas")

        await db.executemany(
            "INSERT OR REPLACE INTO closed_dates "
            "(origem, destino, data_voo, lead_bucket, min_price, med_price, n_obs) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(*key, min(prices), statistics.median(prices), len(prices))
             for key, prices in summary.items()],
        )
        await db.execute("DELETE FROM price_daily WHERE substr(route, -10) < ?", (cutoff,))
        await db.commit()
    return len({key[:3] for key in summary})


async def stats(days: int = STATS_DAYS) -> dict[str, dict]:
    """Per route+date over the window: low, median, sparkline of daily lows, the day the
    low was first seen, and how many days were observed."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT route, dia, price FROM price_daily WHERE dia >= ? ORDER BY route, dia",
            (_cutoff_date(days),),
        ) as cursor:
            rows = await cursor.fetchall()

    daily: dict[str, list[tuple[str, float]]] = {}
    for route, dia, price in rows:
        daily.setdefault(route, []).append((dia, price))

    out: dict[str, dict] = {}
    for route, points in daily.items():
        prices = [p for _d, p in points]
        low = min(prices)
        out[route] = {
            "min": low,
            "med": statistics.median(prices),
            "spark": prices[-SPARK_POINTS:],
            "since": next(d for d, p in points if p == low),
            "n": len(prices),
        }
    return out


async def route_stats() -> dict[str, dict]:
    """Per ORIG|DEST, over every flight date ever seen (live and departed): what the
    route usually costs, by flight month and weekday, and how the price behaves by lead time."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT route, price FROM price_daily") as cur:
            live = await cur.fetchall()
        async with db.execute(
            "SELECT origem, destino, data_voo, lead_bucket, min_price, med_price FROM closed_dates"
        ) as cur:
            closed = await cur.fetchall()

    # Two views of the same flight dates. `lows` is the floor ever seen and only feeds "min";
    # `typical` is what that date usually costs and feeds every median below — a median of
    # floors reads systematically cheaper than the market and makes every live fare look dear.
    lows: dict[str, dict[str, float]] = {}          # route -> flight date -> lowest price
    typical: dict[str, dict[str, float]] = {}       # route -> flight date -> representative price

    live_prices: dict[str, dict[str, list[float]]] = {}
    malformed = 0
    for key, price in live:
        parts = _split_key(key)
        if parts is None:
            malformed += 1
            continue
        origem, destino, data_voo = parts
        live_prices.setdefault(f"{origem}|{destino}", {}).setdefault(data_voo, []).append(price)
    if malformed:
        logger.warning(f"histórico: {malformed} linha(s) de price_daily com chave inválida ignoradas")
    for route, per_date in live_prices.items():
        for data_voo, prices in per_date.items():
            lows.setdefault(route, {})[data_voo] = min(prices)
            typical.setdefault(route, {})[data_voo] = statistics.median(prices)

    buckets: dict[str, dict[int, list[float]]] = {}
    closed_meds: dict[str, dict[str, list[float]]] = {}
    closed_dates_per_route: dict[str, set[str]] = {}
    for origem, destino, data_voo, bucket, min_price, med_price in closed:
        route = f"{origem}|{destino}"
        per_date = lows.setdefault(route, {})
        per_date[data_voo] = min(min_price, per_date.get(data_voo, min_price))
        closed_meds.setdefault(route, {}).setdefault(data_voo, []).append(med_price)
        buckets.setdefault(route, {}).setdefault(bucket, []).append(med_price)
        closed_dates_per_route.setdefault(route, set()).add(data_voo)
    for route, per_date in closed_meds.items():
        reps = typical.setdefault(route, {})
        for data_voo, meds in per_date.items():
            reps.setdefault(data_voo, statistics.median(meds))   # a live date keeps its live median

    def _median_by(per_date: dict[str, float], key_of) -> dict[str, float]:
        groups: dict[str, list[float]] = {}
        for data_voo, price in per_date.items():
            try:
                group = key_of(data_voo)
            except ValueError:      # a date this function cannot parse is dropped, not raised
                continue
            groups.setdefault(group, []).append(price)
        return {k: statistics.median(v) for k, v in groups.items()}

    out: dict[str, dict] = {}
    for route, per_date in lows.items():
        reps = typical.get(route, {})
        out[route] = {
            "med": statistics.median(reps.values()),
            "min": min(per_date.values()),
            "n_dates": len(per_date),
            "by_month": _median_by(reps, lambda d: d[5:7]),
            "by_dow": _median_by(reps, lambda d: str(date.fromisoformat(d).weekday())),
            "lead_curve": [
                {"bucket": b, "med": statistics.median(v), "n": len(v)}
                for b, v in sorted(buckets.get(route, {}).items())
            ],
            "n_closed": len(closed_dates_per_route.get(route, ())),
        }
    return out


async def all_series(max_points: int = 90) -> dict[str, list[list]]:
    """Daily series of every live route+date, oldest first, for the panel charts."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT route, dia, price FROM price_daily WHERE dia >= ? ORDER BY route, dia",
            (_cutoff_date(max_points),),
        ) as cur:
            rows = await cur.fetchall()
    out: dict[str, list[list]] = {}
    for route, dia, price in rows:
        out.setdefault(route, []).append([dia, price])
    return {route: points[-max_points:] for route, points in out.items()}


@dataclass(frozen=True)
class HistoryContext:
    delta_pct: int          # fare vs the median it is compared against; negative = cheaper
    window_days: int
    is_lowest: bool         # fare matches or beats the lowest price in the window
    since: str | None       # day that low was first seen; None at route scope
    scope: str              # "data" = this exact flight date, "rota" = the whole route


def context_for(flight, stats: dict[str, dict], route_stats: dict[str, dict]) -> HistoryContext | None:
    """How a fare compares with history: the exact date when it has two or more days of
    observations, else the route median, else nothing."""
    if flight.price is None or flight.price <= 0:
        return None
    entry = stats.get(f"{flight.origin}|{flight.destination}|{flight.departure_date.isoformat()}")
    if entry and entry["n"] >= 2:
        return HistoryContext(
            delta_pct=round((flight.price - entry["med"]) / entry["med"] * 100),
            window_days=STATS_DAYS,
            is_lowest=flight.price <= entry["min"],
            since=entry["since"],
            scope="data",
        )
    route = route_stats.get(f"{flight.origin}|{flight.destination}")
    if route and route["n_dates"] >= MIN_ROUTE_DATES:
        return HistoryContext(
            delta_pct=round((flight.price - route["med"]) / route["med"] * 100),
            window_days=STATS_DAYS, is_lowest=False, since=None, scope="rota",
        )
    return None
