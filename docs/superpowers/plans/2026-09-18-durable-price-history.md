# Durable Price History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make price history survive cache loss, keep it long enough to describe routes and lead times, and surface it in Telegram messages and in a real chart in the new panel.

**Architecture:** `history.py` moves to two sqlite layers: `price_daily` (one row per route+date per day, while the flight is in the future) and `closed_dates` (permanent per-lead-bucket summary once the flight date passes). The database is gzipped, encrypted and mirrored to a GitHub Release asset each successful cycle. The cycle loads stats once up front, passes context to alert formatters, and writes a second encrypted file (`history.enc.json`) that the new panel fetches lazily to draw charts.

**Tech Stack:** Python 3.11, aiosqlite, cryptography (PBKDF2 + AES-GCM), pytest + pytest-asyncio (auto mode), `gh` CLI in GitHub Actions, vanilla JS + WebCrypto + `DecompressionStream`, inline SVG.

**Spec:** `docs/superpowers/specs/2026-09-18-durable-price-history-design.md`

## Global Constraints

- Work on branch `feat/durable-price-history` (already exists, rebased on master).
- Run tests with `python -m pytest -q`. On Windows wrap with `timeout 100` in Git Bash; a failing async test can leave an aiosqlite thread alive and hang the interpreter at exit.
- Tests never touch the real `data/cache.db` or `./deals.json`: `tests/conftest.py` autouse fixtures patch `cache.DB_PATH`, `history.DB_PATH` and `cycle.DEALS_PATH`. Task 8 adds `cycle.HISTORY_PATH` to that fixture.
- `history.deal_key(deal)` stays `"ORIG|DEST|YYYY-MM-DD"`. Route key is `"ORIG|DEST"`.
- Stats window: **60 days**. Sparkline: last **14** daily points. Series shipped to the panel: last **90** points per key.
- `LEAD_BUCKETS = [(0,7), (8,14), (15,30), (31,60), (61,90), (91,120), (121,180)]`; lead beyond 180 days falls in the last bucket.
- Delta within ±3% is "na média" (same threshold the panel already uses).
- "When to buy" is shown only for routes with **≥ 20 closed dates** and data in **≥ 4 buckets**.
- Encrypted payloads: `v: 1` = raw plaintext, `v: 2` = gzip-then-encrypt with `"enc": "gzip"`. Readers must accept both.
- The repository is public: nothing leaves the runner unencrypted. Password = `PANEL_PASSWORD` secret.
- No alert is added, removed or re-keyed. Dedup keys are untouched. Round-trip alerts and records get no history context.
- The classic panel (`web/classic/`) gets only the shared decrypt routine; no new features.
- Portuguese for user-facing copy, English for code, comments and commit messages. End commit messages with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Do not push. The owner pushes after reviewing.

## File Structure

| File | Responsibility |
|---|---|
| `history.py` (modify) | Both sqlite layers, migration, rollup, `stats`, `route_stats`, `all_series`, `HistoryContext`, `context_for` |
| `scripts/encrypt_deals.py` (modify) | `encrypt_bytes` / `decrypt_bytes`, gzip v2 payloads, CLI encrypts `deals.json` and `history.json` |
| `scripts/history_backup.py` (create) | `restore` / `backup` of `data/cache.db` to the `history-db` release |
| `panel.py` (modify) | Route-level fields on deals; `build_history_payload`, `write_history` |
| `telegram_bot.py` (modify) | `format_context_line`; optional `context` on the three formatters/senders |
| `cycle.py` (modify) | New ordering, context wiring, `HISTORY_PATH` |
| `web/switch.js` (modify) | `PanelCrypto.load(url, password)`: fetch, decrypt, inflate v2 |
| `web/app.js`, `web/style.css` (modify) | Lazy history load, date chart, route section, "vs. rota" |
| `web/classic/app.js` (modify) | Use `PanelCrypto.load` |
| `.github/workflows/azul-alert.yml` (modify) | Restore/backup steps, `contents: write`, ship `history.enc.json` |

---

### Task 1: `price_daily` — one row per key per day, with migration

**Files:**
- Modify: `history.py`
- Test: `tests/test_history.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `history.init_db()`, `history.record(deals, seen_at=None) -> int` (same signature; now upserts the daily minimum). Table `price_daily(route, dia, price)`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_history.py`:

```python
import aiosqlite


async def _rows(sql):
    async with aiosqlite.connect(history.DB_PATH) as db:
        async with db.execute(sql) as cur:
            return await cur.fetchall()


async def test_three_cycles_on_one_day_collapse_into_one_row_holding_the_minimum():
    await history.init_db()
    for hour, price in ((8, 450.0), (14, 380.0), (20, 410.0)):
        await history.record([_deal(preco=price)], seen_at=_at(2, hour=hour))
    assert await _rows("SELECT route, price FROM price_daily") == [("CNF|SJK|2026-09-10", 380.0)]


async def test_init_db_migrates_the_old_per_cycle_table_once():
    async with aiosqlite.connect(history.DB_PATH) as db:
        await db.execute(
            "CREATE TABLE price_history (id INTEGER PRIMARY KEY, route TEXT NOT NULL, "
            "price REAL NOT NULL, seen_at TEXT NOT NULL)")
        await db.executemany(
            "INSERT INTO price_history (route, price, seen_at) VALUES (?, ?, ?)",
            [("CNF|SJK|2026-09-10", 450.0, "2026-09-01T08:00:00+00:00"),
             ("CNF|SJK|2026-09-10", 380.0, "2026-09-01T20:00:00+00:00"),
             ("CNF|SJK|2026-09-10", 500.0, "2026-09-02T08:00:00+00:00")])
        await db.commit()

    await history.init_db()
    await history.init_db()   # second run must be a no-op

    assert await _rows("SELECT dia, price FROM price_daily ORDER BY dia") == [
        ("2026-09-01", 380.0), ("2026-09-02", 500.0)]
    assert await _rows("SELECT name FROM sqlite_master WHERE name = 'price_history'") == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `timeout 100 python -m pytest tests/test_history.py -q`
Expected: the two new tests FAIL with `no such table: price_daily`.

- [ ] **Step 3: Implement** — in `history.py` replace `init_db` and `record`, and drop the `RETENTION_DAYS` constant (its user, `purge_old`, goes away in Task 2; leave `purge_old` in place for now so the suite stays green):

```python
STATS_DAYS = 60


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
```

Add at the top of the file: `import logging` and `logger = logging.getLogger(__name__)`.

Point the existing `stats` and `purge_old` at the new table so every older test keeps passing:

```python
async def purge_old(days: int = 60) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM price_daily WHERE dia < ?", (_cutoff_iso(days)[:10],))
        await db.commit()
```

In `stats`, replace the SQL with:

```sql
SELECT route, dia, price FROM price_daily WHERE dia >= ? ORDER BY route, dia
```

and pass `(_cutoff_iso(days)[:10],)`.

- [ ] **Step 4: Run the whole history file**

Run: `timeout 100 python -m pytest tests/test_history.py tests/test_cycle_history.py -q`
Expected: all PASS (the older tests pin `days=` explicitly where the window matters).

- [ ] **Step 5: Commit**

```bash
git add history.py tests/test_history.py
git commit -m "feat(history): one row per route+date per day, migrating the per-cycle table"
```

---

### Task 2: `closed_dates` — permanent summary of flights that already left

**Files:**
- Modify: `history.py`
- Test: `tests/test_history_rollup.py` (create), `tests/test_history.py` (remove the `purge_old` test)

**Interfaces:**
- Consumes: `price_daily` from Task 1.
- Produces: `history.LEAD_BUCKETS`, `history.lead_bucket(days: int) -> int`, `history.rollup_closed(today: date | None = None) -> int` (number of route+date keys closed). Table `closed_dates(origem, destino, data_voo, lead_bucket, min_price, n_obs)`. `purge_old` is deleted.

- [ ] **Step 1: Write the failing tests** — create `tests/test_history_rollup.py`:

```python
from datetime import date

import aiosqlite
import pytest

import history


async def _seed(rows):
    await history.init_db()
    async with aiosqlite.connect(history.DB_PATH) as db:
        await db.executemany("INSERT INTO price_daily (route, dia, price) VALUES (?, ?, ?)", rows)
        await db.commit()


async def _all(sql):
    async with aiosqlite.connect(history.DB_PATH) as db:
        async with db.execute(sql) as cur:
            return await cur.fetchall()


@pytest.mark.parametrize("days, bucket", [
    (0, 0), (7, 0), (8, 1), (14, 1), (15, 2), (30, 2), (31, 3), (60, 3),
    (61, 4), (90, 4), (91, 5), (120, 5), (121, 6), (180, 6), (181, 6), (400, 6),
])
def test_lead_bucket_boundaries(days, bucket):
    assert history.lead_bucket(days) == bucket


async def test_rollup_summarises_a_departed_flight_per_bucket_and_drops_its_detail():
    await _seed([
        ("CNF|GIG|2026-09-10", "2026-09-08", 300.0),   # lead 2  -> bucket 0
        ("CNF|GIG|2026-09-10", "2026-09-05", 280.0),   # lead 5  -> bucket 0
        ("CNF|GIG|2026-09-10", "2026-08-20", 410.0),   # lead 21 -> bucket 2
    ])
    closed = await history.rollup_closed(today=date(2026, 9, 11))

    assert closed == 1
    assert await _all("SELECT origem, destino, data_voo, lead_bucket, min_price, n_obs "
                      "FROM closed_dates ORDER BY lead_bucket") == [
        ("CNF", "GIG", "2026-09-10", 0, 280.0, 2),
        ("CNF", "GIG", "2026-09-10", 2, 410.0, 1),
    ]
    assert await _all("SELECT * FROM price_daily") == []


async def test_rollup_leaves_flights_departing_today_or_later_alone():
    await _seed([("CNF|GIG|2026-09-11", "2026-09-01", 300.0),
                 ("CNF|GIG|2026-12-01", "2026-09-01", 500.0)])
    assert await history.rollup_closed(today=date(2026, 9, 11)) == 0
    assert len(await _all("SELECT * FROM price_daily")) == 2


async def test_rollup_is_safe_to_run_twice():
    await _seed([("CNF|GIG|2026-09-10", "2026-09-08", 300.0)])
    await history.rollup_closed(today=date(2026, 9, 11))
    await history.rollup_closed(today=date(2026, 9, 11))
    assert len(await _all("SELECT * FROM closed_dates")) == 1
```

- [ ] **Step 2: Run to verify they fail**

Run: `timeout 100 python -m pytest tests/test_history_rollup.py -q`
Expected: FAIL with `module 'history' has no attribute 'lead_bucket'`.

- [ ] **Step 3: Implement** — in `history.py`. Add `from datetime import date` to the imports. Add to `init_db`, before the migration block:

```python
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
```

Delete `purge_old` and add:

```python
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
```

In `tests/test_history.py` delete `test_purge_old_deletes_observations_past_the_retention_window`.
In `cycle.py` replace `await history.purge_old()` with `await history.rollup_closed(today)`.

- [ ] **Step 4: Run**

Run: `timeout 100 python -m pytest -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add history.py cycle.py tests/test_history.py tests/test_history_rollup.py
git commit -m "feat(history): roll departed flights into a permanent per-lead-bucket summary"
```

---

### Task 3: Queries — longer `stats`, `route_stats`, `all_series`, `context_for`

**Files:**
- Modify: `history.py`
- Test: `tests/test_history_queries.py` (create)

**Interfaces:**
- Consumes: both tables.
- Produces:
  - `history.stats(days=60) -> dict[str, dict]`; each entry `{"min": float, "med": float, "spark": list[float], "since": "YYYY-MM-DD", "n": int}`.
  - `history.route_stats() -> dict[str, dict]` keyed `"ORIG|DEST"`; each entry `{"med": float, "min": float, "n_dates": int, "by_month": {"01".."12": float}, "by_dow": {"0".."6": float}` (Monday = "0")`, "lead_curve": [{"bucket": int, "med": float, "n": int}], "n_closed": int}`.
  - `history.all_series(max_points=90) -> dict[str, list[list]]` — `[[dia, price], ...]` oldest first.
  - `history.HistoryContext(delta_pct: int, window_days: int, is_lowest: bool, since: str | None, scope: str)` and `history.context_for(flight, stats, route_stats) -> HistoryContext | None`.
  - `history.MIN_ROUTE_DATES = 5`.

- [ ] **Step 1: Write the failing tests** — create `tests/test_history_queries.py`:

```python
from datetime import date, datetime, time, timedelta, timezone

import aiosqlite

import history
from airlines.base import Flight


def _at(days_ago, hour=12):
    day = datetime.now(timezone.utc).date() - timedelta(days=days_ago)
    return datetime.combine(day, time(hour), tzinfo=timezone.utc)


def _deal(destino="GIG", data="2027-01-15", preco=300.0):
    return {"origem": "CNF", "destino": destino, "data": data, "preco": preco}


async def test_stats_reports_when_the_window_low_was_first_seen_and_how_many_days():
    await history.init_db()
    for days_ago, price in ((5, 400.0), (4, 300.0), (3, 350.0), (2, 300.0)):
        await history.record([_deal(preco=price)], seen_at=_at(days_ago))
    entry = (await history.stats())["CNF|GIG|2027-01-15"]
    assert entry["min"] == 300.0 and entry["n"] == 4
    assert entry["since"] == _at(4).date().isoformat()


async def test_stats_window_defaults_to_sixty_days():
    await history.init_db()
    await history.record([_deal(preco=100.0)], seen_at=_at(59))
    await history.record([_deal(preco=900.0)], seen_at=_at(61))
    assert (await history.stats())["CNF|GIG|2027-01-15"]["min"] == 100.0


async def test_route_stats_uses_the_lowest_price_of_each_flight_date():
    await history.init_db()
    # 2027-01-15 is a Friday (weekday 4); 2027-02-01 is a Monday (weekday 0).
    await history.record([_deal(data="2027-01-15", preco=400.0)], seen_at=_at(3))
    await history.record([_deal(data="2027-01-15", preco=300.0)], seen_at=_at(2))
    await history.record([_deal(data="2027-02-01", preco=500.0)], seen_at=_at(2))
    r = (await history.route_stats())["CNF|GIG"]
    assert (r["min"], r["med"], r["n_dates"]) == (300.0, 400.0, 2)
    assert r["by_month"] == {"01": 300.0, "02": 500.0}
    assert r["by_dow"] == {"4": 300.0, "0": 500.0}
    assert r["lead_curve"] == [] and r["n_closed"] == 0


async def test_route_stats_merges_departed_flights_and_builds_the_lead_curve():
    await history.init_db()
    async with aiosqlite.connect(history.DB_PATH) as db:
        await db.executemany("INSERT INTO closed_dates VALUES (?, ?, ?, ?, ?, ?)", [
            ("CNF", "GIG", "2026-08-01", 0, 600.0, 3),
            ("CNF", "GIG", "2026-08-01", 3, 350.0, 9),
            ("CNF", "GIG", "2026-08-02", 3, 450.0, 9),
        ])
        await db.commit()
    await history.record([_deal(preco=300.0)], seen_at=_at(1))
    r = (await history.route_stats())["CNF|GIG"]
    assert r["n_dates"] == 3 and r["n_closed"] == 2
    assert r["min"] == 300.0 and r["med"] == 350.0      # per-date lows: 300, 350, 450
    assert r["lead_curve"] == [{"bucket": 0, "med": 600.0, "n": 1},
                               {"bucket": 3, "med": 400.0, "n": 2}]


async def test_all_series_is_oldest_first_and_capped():
    await history.init_db()
    for i in range(5):
        await history.record([_deal(preco=100.0 + i)], seen_at=_at(4 - i))
    s = (await history.all_series(max_points=3))["CNF|GIG|2027-01-15"]
    assert [p for _d, p in s] == [102.0, 103.0, 104.0]
    assert s[0][0] < s[-1][0]


def _flight(price):
    return Flight("CNF", "GIG", "Azul", date(2027, 1, 15), "08h00", "09h00", price, True, 0, "u")


def test_context_prefers_the_history_of_the_exact_date():
    stats = {"CNF|GIG|2027-01-15": {"min": 300.0, "med": 400.0, "spark": [400.0, 300.0],
                                    "since": "2026-09-01", "n": 2}}
    ctx = history.context_for(_flight(280.0), stats, {})
    assert ctx == history.HistoryContext(-30, 60, True, "2026-09-01", "data")


def test_context_falls_back_to_the_route_when_the_date_is_new():
    routes = {"CNF|GIG": {"med": 500.0, "min": 320.0, "n_dates": 40}}
    ctx = history.context_for(_flight(400.0), {}, routes)
    assert (ctx.delta_pct, ctx.scope, ctx.is_lowest, ctx.since) == (-20, "rota", False, None)


def test_context_is_none_without_enough_history():
    thin = {"CNF|GIG": {"med": 500.0, "min": 320.0, "n_dates": history.MIN_ROUTE_DATES - 1}}
    one_point = {"CNF|GIG|2027-01-15": {"min": 300.0, "med": 300.0, "spark": [300.0],
                                        "since": "2026-09-01", "n": 1}}
    assert history.context_for(_flight(400.0), one_point, thin) is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `timeout 100 python -m pytest tests/test_history_queries.py -q`
Expected: FAIL (`KeyError: 'n'`, `no attribute 'route_stats'`, ...).

- [ ] **Step 3: Implement** — in `history.py`. Add `from dataclasses import dataclass` to the imports. Replace `stats` and add the rest:

```python
MIN_ROUTE_DATES = 5     # flight dates a route needs before its median means anything


async def stats(days: int = STATS_DAYS) -> dict[str, dict]:
    """Per route+date over the window: low, median, sparkline of daily lows, the day the
    low was first seen, and how many days were observed."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT route, dia, price FROM price_daily WHERE dia >= ? ORDER BY route, dia",
            (_cutoff_iso(days)[:10],),
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
        async with db.execute("SELECT route, MIN(price) FROM price_daily GROUP BY route") as cur:
            live = await cur.fetchall()
        async with db.execute(
            "SELECT origem, destino, data_voo, lead_bucket, min_price FROM closed_dates"
        ) as cur:
            closed = await cur.fetchall()

    lows: dict[str, dict[str, float]] = {}          # route -> flight date -> lowest price
    for key, price in live:
        origem, destino, data_voo = key.split("|")
        lows.setdefault(f"{origem}|{destino}", {})[data_voo] = price

    buckets: dict[str, dict[int, list[float]]] = {}
    closed_dates_per_route: dict[str, set[str]] = {}
    for origem, destino, data_voo, bucket, price in closed:
        route = f"{origem}|{destino}"
        per_date = lows.setdefault(route, {})
        per_date[data_voo] = min(price, per_date.get(data_voo, price))
        buckets.setdefault(route, {}).setdefault(bucket, []).append(price)
        closed_dates_per_route.setdefault(route, set()).add(data_voo)

    def _median_by(per_date: dict[str, float], key_of) -> dict[str, float]:
        groups: dict[str, list[float]] = {}
        for data_voo, price in per_date.items():
            groups.setdefault(key_of(data_voo), []).append(price)
        return {k: statistics.median(v) for k, v in groups.items()}

    out: dict[str, dict] = {}
    for route, per_date in lows.items():
        prices = list(per_date.values())
        out[route] = {
            "med": statistics.median(prices),
            "min": min(prices),
            "n_dates": len(prices),
            "by_month": _median_by(per_date, lambda d: d[5:7]),
            "by_dow": _median_by(per_date, lambda d: str(date.fromisoformat(d).weekday())),
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
        async with db.execute("SELECT route, dia, price FROM price_daily ORDER BY route, dia") as cur:
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
```

- [ ] **Step 4: Run**

Run: `timeout 100 python -m pytest -q`
Expected: all PASS. `tests/test_panel_history.py` still passes because `enrich_with_history` only reads `min`, `med`, `spark`.

- [ ] **Step 5: Commit**

```bash
git add history.py tests/test_history_queries.py
git commit -m "feat(history): route-level stats, lead curve, series and alert context"
```

---

### Task 4: gzip-then-encrypt payloads (`v: 2`)

**Files:**
- Modify: `scripts/encrypt_deals.py`
- Test: `tests/test_encrypt_deals.py`

**Interfaces:**
- Produces: `encrypt_bytes(plaintext: bytes, password: str, compress: bool = True) -> dict`, `decrypt_bytes(payload: dict, password: str) -> bytes` (inflates when `payload.get("enc") == "gzip"`), `encrypt_file(in_path, out_path, password) -> str` (now v2), `decrypt(payload, password) -> bytes` kept as an alias of `decrypt_bytes`. CLI encrypts `deals.json` and, when present, `history.json`.

- [ ] **Step 1: Write the failing tests** — in `tests/test_encrypt_deals.py` change the existing assertion `payload["v"] == 1` to `payload["v"] == 2 and payload["enc"] == "gzip"`, update the import line to `from scripts.encrypt_deals import encrypt_file, decrypt, encrypt_bytes, decrypt_bytes`, and append:

```python
def test_v2_payload_is_much_smaller_for_repetitive_json():
    plain = json.dumps({"deals": [{"origem": "CNF", "destino": "GIG", "preco": 300.0}] * 2000}).encode()
    v1 = encrypt_bytes(plain, "s", compress=False)
    v2 = encrypt_bytes(plain, "s")
    assert len(v2["ciphertext"]) < len(v1["ciphertext"]) / 5
    assert decrypt_bytes(v2, "s") == plain


def test_v1_payloads_written_before_compression_still_decrypt():
    v1 = encrypt_bytes(b'{"deals":[]}', "s", compress=False)
    assert v1["v"] == 1 and "enc" not in v1
    assert decrypt_bytes(v1, "s") == b'{"deals":[]}'
```

- [ ] **Step 2: Run to verify they fail**

Run: `timeout 100 python -m pytest tests/test_encrypt_deals.py -q`
Expected: FAIL with `ImportError: cannot import name 'encrypt_bytes'`.

- [ ] **Step 3: Implement** — replace everything below `_derive_key` in `scripts/encrypt_deals.py`:

```python
def encrypt_bytes(plaintext: bytes, password: str, compress: bool = True) -> dict:
    """AES-GCM under a PBKDF2 key. Ciphertext does not compress in transit, so the
    plaintext is gzipped first (payload v2); compress=False writes the old v1 shape."""
    body = gzip.compress(plaintext, mtime=0) if compress else plaintext
    salt = os.urandom(16)
    iv = os.urandom(12)
    key = _derive_key(password, salt, ITERATIONS)
    payload = {
        "v": 2 if compress else 1,
        "kdf": "PBKDF2-SHA256",
        "iterations": ITERATIONS,
        "salt": base64.b64encode(salt).decode("ascii"),
        "iv": base64.b64encode(iv).decode("ascii"),
        "ciphertext": base64.b64encode(AESGCM(key).encrypt(iv, body, None)).decode("ascii"),
    }
    if compress:
        payload["enc"] = "gzip"
    return payload


def decrypt_bytes(payload: dict, password: str) -> bytes:
    salt = base64.b64decode(payload["salt"])
    iv = base64.b64decode(payload["iv"])
    key = _derive_key(password, salt, payload["iterations"])
    body = AESGCM(key).decrypt(iv, base64.b64decode(payload["ciphertext"]), None)
    return gzip.decompress(body) if payload.get("enc") == "gzip" else body


decrypt = decrypt_bytes   # older name, still imported by tests and scripts


def encrypt_file(in_path: str, out_path: str, password: str) -> str:
    with open(in_path, "rb") as fh:
        payload = encrypt_bytes(fh.read(), password)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    return out_path


if __name__ == "__main__":
    password = os.environ["PANEL_PASSWORD"]
    encrypt_file("deals.json", "deals.enc.json", password)
    if os.path.exists("history.json"):
        encrypt_file("history.json", "history.enc.json", password)
```

Add `import gzip` at the top.

- [ ] **Step 4: Run**

Run: `timeout 100 python -m pytest tests/test_encrypt_deals.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/encrypt_deals.py tests/test_encrypt_deals.py
git commit -m "feat(crypto): gzip before encrypting (payload v2), v1 still readable"
```

> The panels cannot read v2 until Task 9. Tasks 4–11 ship together in one merge, so production never sees a v2 file with a v1-only reader.

---

### Task 5: Release backup of the database

**Files:**
- Create: `scripts/history_backup.py`
- Test: `tests/test_history_backup.py` (create)

**Interfaces:**
- Consumes: `encrypt_bytes`, `decrypt_bytes` from Task 4.
- Produces: `restore(db_path, password, run=subprocess.run) -> bool`, `backup(db_path, password, run=subprocess.run) -> bool`; CLI `python scripts/history_backup.py restore|backup`. Constants `TAG = "history-db"`, `ASSET = "cache.db.gz.enc"`. Both functions never raise.

- [ ] **Step 1: Write the failing tests** — create `tests/test_history_backup.py`:

```python
import json
import subprocess
from pathlib import Path

from scripts import history_backup as hb
from scripts.encrypt_deals import encrypt_bytes


class FakeGh:
    """Stands in for subprocess.run; records calls and plays the part of `gh`."""

    def __init__(self, asset: bytes | None = None, fail: set[str] = frozenset()):
        self.asset, self.fail, self.calls = asset, fail, []

    def __call__(self, cmd, **kwargs):
        self.calls.append(cmd)
        verb = cmd[2]
        if verb in self.fail:
            raise subprocess.CalledProcessError(1, cmd, stderr=b"boom")
        if verb == "download":
            if self.asset is None:
                raise subprocess.CalledProcessError(1, cmd, stderr=b"release not found")
            out_dir = Path(cmd[cmd.index("--dir") + 1])
            (out_dir / hb.ASSET).write_bytes(self.asset)
        return subprocess.CompletedProcess(cmd, 0)


def test_backup_then_restore_round_trips_the_database(tmp_path):
    db = tmp_path / "cache.db"
    db.write_bytes(b"SQLite format 3\x00" + b"x" * 5000)
    uploaded = {}

    def gh(cmd, **kwargs):
        if cmd[2] == "upload":
            uploaded["bytes"] = Path(cmd[4]).read_bytes()
        return subprocess.CompletedProcess(cmd, 0)

    assert hb.backup(db, "segredo", run=gh) is True
    assert b"SQLite format" not in uploaded["bytes"]          # never leaves in the clear

    restored = tmp_path / "restored.db"
    assert hb.restore(restored, "segredo", run=FakeGh(asset=uploaded["bytes"])) is True
    assert restored.read_bytes() == db.read_bytes()


def test_restore_without_a_release_starts_empty_and_does_not_raise(tmp_path):
    target = tmp_path / "cache.db"
    assert hb.restore(target, "segredo", run=FakeGh(asset=None)) is False
    assert not target.exists()


def test_restore_with_a_corrupt_or_foreign_asset_leaves_nothing_behind(tmp_path):
    target = tmp_path / "cache.db"
    wrong_key = json.dumps(encrypt_bytes(b"data", "outra-senha")).encode()
    assert hb.restore(target, "segredo", run=FakeGh(asset=b"not json")) is False
    assert hb.restore(target, "segredo", run=FakeGh(asset=wrong_key)) is False
    assert not target.exists()


def test_backup_creates_the_release_when_the_upload_finds_none(tmp_path):
    db = tmp_path / "cache.db"
    db.write_bytes(b"data")
    state = {"created": False}
    verbs = []

    def gh(cmd, **kwargs):
        verbs.append(cmd[2])
        if cmd[2] == "upload" and not state["created"]:
            raise subprocess.CalledProcessError(1, cmd, stderr=b"release not found")
        if cmd[2] == "create":
            state["created"] = True
        return subprocess.CompletedProcess(cmd, 0)

    assert hb.backup(db, "segredo", run=gh) is True
    assert verbs == ["upload", "create", "upload"]


def test_backup_reports_failure_without_raising(tmp_path):
    db = tmp_path / "cache.db"
    db.write_bytes(b"data")
    assert hb.backup(db, "segredo", run=FakeGh(fail={"upload", "create"})) is False
    assert hb.backup(tmp_path / "missing.db", "segredo", run=FakeGh()) is False
```

- [ ] **Step 2: Run to verify they fail**

Run: `timeout 100 python -m pytest tests/test_history_backup.py -q`
Expected: FAIL with `ImportError: cannot import name 'history_backup'`.

- [ ] **Step 3: Implement** — create `scripts/history_backup.py`:

```python
"""Durable copy of data/cache.db in a GitHub Release asset.

actions/cache is the fast path but is evicted after 7 idle days. After every good cycle
the database is gzipped, encrypted with the panel password (the repo is public) and
uploaded over the previous copy; a run that starts with no cache downloads it back.
Neither direction may ever fail the job.
"""
import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.encrypt_deals import decrypt_bytes, encrypt_bytes  # noqa: E402

logger = logging.getLogger("history_backup")

TAG = "history-db"
ASSET = "cache.db.gz.enc"
DB_PATH = Path("data/cache.db")


def restore(db_path: Path, password: str, run=subprocess.run) -> bool:
    db_path = Path(db_path)
    with tempfile.TemporaryDirectory() as tmp:
        try:
            run(["gh", "release", "download", TAG, "--pattern", ASSET, "--dir", tmp],
                check=True, capture_output=True)
            payload = json.loads((Path(tmp) / ASSET).read_text(encoding="utf-8"))
            data = decrypt_bytes(payload, password)
        except Exception as e:                      # missing release, bad asset, wrong key...
            logger.warning(f"backup do histórico não restaurado, começando vazio: {e!r}")
            return False
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.write_bytes(data)
    logger.info(f"histórico restaurado da release {TAG}: {len(data)} bytes")
    return True


def backup(db_path: Path, password: str, run=subprocess.run) -> bool:
    db_path = Path(db_path)
    if not db_path.exists():
        logger.warning(f"{db_path} não existe; nada para salvar")
        return False
    with tempfile.TemporaryDirectory() as tmp:
        asset = Path(tmp) / ASSET
        asset.write_text(json.dumps(encrypt_bytes(db_path.read_bytes(), password)), encoding="utf-8")
        upload = ["gh", "release", "upload", TAG, str(asset), "--clobber"]
        try:
            try:
                run(upload, check=True, capture_output=True)
            except subprocess.CalledProcessError:
                run(["gh", "release", "create", TAG, "--title", "Price history backup",
                     "--notes", "Encrypted sqlite backup, overwritten after every cycle."],
                    check=True, capture_output=True)
                run(upload, check=True, capture_output=True)
        except Exception as e:
            logger.warning(f"backup do histórico falhou: {e!r}")
            return False
    logger.info(f"histórico salvo na release {TAG}")
    return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    if action not in ("restore", "backup"):
        sys.exit("usage: history_backup.py restore|backup")
    (restore if action == "restore" else backup)(DB_PATH, os.environ["PANEL_PASSWORD"])
    sys.exit(0)     # a failed backup or restore must never turn the run red
```

If `scripts/__init__.py` does not exist, the existing `from scripts.encrypt_deals import ...` in tests already works through the rootdir; do not add one.

- [ ] **Step 4: Run**

Run: `timeout 100 python -m pytest tests/test_history_backup.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/history_backup.py tests/test_history_backup.py
git commit -m "feat(history): encrypted backup and restore through a GitHub release asset"
```

---

### Task 6: Panel outputs — route-level fields and `history.json`

**Files:**
- Modify: `panel.py`
- Test: `tests/test_panel_history.py`

**Interfaces:**
- Consumes: `stats` / `route_stats` / `all_series` shapes from Task 3, `history.MIN_ROUTE_DATES`.
- Produces: `panel.enrich_with_history(deals, stats, route_stats=None) -> int` (second argument optional so existing callers keep working); new deal fields `hist_dias`, `hist_desde`, `rota_med`, `rota_min`, `rota_delta_pct`. `panel.build_history_payload(route_stats, series, generated_at=None) -> dict`, `panel.write_history(payload, path) -> str`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_panel_history.py`:

```python
import json
from datetime import datetime, timezone


def _route(med=500.0, min_=320.0, n_dates=40):
    return {"CNF|SJK": {"med": med, "min": min_, "n_dates": n_dates, "by_month": {"09": med},
                        "by_dow": {"3": med}, "lead_curve": [], "n_closed": 0}}


def test_enrich_adds_observation_count_and_first_seen_day():
    deal = _deal(preco=352.0)
    stats = _stats()
    stats["CNF|SJK|2026-09-10"].update(since="2026-08-30", n=2)
    panel.enrich_with_history([deal], stats, _route())
    assert deal["hist_dias"] == 2 and deal["hist_desde"] == "2026-08-30"


def test_a_never_seen_date_still_gets_a_route_level_verdict():
    deal = _deal(preco=400.0)
    panel.enrich_with_history([deal], {}, _route(med=500.0, min_=320.0))
    assert (deal["rota_med"], deal["rota_min"], deal["rota_delta_pct"]) == (500.0, 320.0, -20)
    assert "delta_pct" not in deal and "spark" not in deal


def test_route_fields_are_withheld_while_the_route_is_thin():
    deal = _deal(preco=400.0)
    panel.enrich_with_history([deal], {}, _route(n_dates=4))
    assert "rota_med" not in deal


def test_round_trips_get_no_route_fields():
    deal = _deal(preco=2900.0, tipo="roundtrip")
    panel.enrich_with_history([deal], {}, _route())
    assert "rota_med" not in deal


def test_history_payload_and_file(tmp_path):
    payload = panel.build_history_payload(
        _route(), {"CNF|SJK|2026-09-10": [["2026-09-01", 400.0], ["2026-09-02", 300.0]]},
        generated_at=datetime(2026, 9, 18, 11, 0, tzinfo=timezone.utc))
    assert payload["gerado_em"] == "2026-09-18T11:00:00Z"
    assert payload["rotas"]["CNF|SJK"]["med"] == 500.0
    assert payload["series"]["CNF|SJK|2026-09-10"][-1] == ["2026-09-02", 300.0]

    out = tmp_path / "history.json"
    panel.write_history(payload, str(out))
    assert json.loads(out.read_text(encoding="utf-8")) == payload
```

- [ ] **Step 2: Run to verify they fail**

Run: `timeout 100 python -m pytest tests/test_panel_history.py -q`
Expected: FAIL with `TypeError: enrich_with_history() takes 2 positional arguments but 3 were given`.

- [ ] **Step 3: Implement** — in `panel.py` replace `enrich_with_history` and add the two writers:

```python
def enrich_with_history(deals: list[dict], stats: dict[str, dict],
                        route_stats: dict[str, dict] | None = None) -> int:
    """Attach history to each one-way deal: its own route+date series (low, median,
    sparkline, gap to the median) when there are two or more days of observations, and
    the route-level median and floor whenever the route has enough flight dates — so a
    date never seen before still gets a verdict. Round-trip records are skipped: their
    `preco` is a two-leg total. Returns how many deals got a date-level series."""
    route_stats = route_stats or {}
    enriched = 0
    for deal in deals:
        if deal.get("tipo") == "roundtrip":
            continue
        route = route_stats.get(f"{deal['origem']}|{deal['destino']}")
        if route and route["n_dates"] >= history.MIN_ROUTE_DATES:
            deal["rota_med"] = route["med"]
            deal["rota_min"] = route["min"]
            deal["rota_delta_pct"] = round((deal["preco"] - route["med"]) / route["med"] * 100)

        entry = stats.get(history.deal_key(deal))
        if entry is None or len(entry["spark"]) < 2:
            continue
        deal["hist_min"] = entry["min"]
        deal["hist_med"] = entry["med"]
        deal["spark"] = entry["spark"]
        deal["delta_pct"] = round((deal["preco"] - entry["med"]) / entry["med"] * 100)
        deal["menor_hist"] = deal["preco"] <= entry["min"]
        if "n" in entry:
            deal["hist_dias"] = entry["n"]
            deal["hist_desde"] = entry["since"]
        enriched += 1
    return enriched


def build_history_payload(route_stats: dict[str, dict], series: dict[str, list[list]],
                          generated_at: datetime | None = None) -> dict:
    """What the panel downloads lazily to draw charts: per-route summary plus the daily
    series of every live route+date."""
    ts = generated_at or datetime.now(timezone.utc)
    return {"gerado_em": ts.strftime("%Y-%m-%dT%H:%M:%SZ"), "rotas": route_stats, "series": series}


def write_history(payload: dict, path: str) -> str:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    return path
```

- [ ] **Step 4: Run**

Run: `timeout 100 python -m pytest tests/test_panel_history.py tests/test_panel.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add panel.py tests/test_panel_history.py
git commit -m "feat(panel): route-level verdict on every deal and a history payload for charts"
```

---

### Task 7: Telegram context line

**Files:**
- Modify: `telegram_bot.py`
- Test: `tests/test_telegram_context.py` (create)

**Interfaces:**
- Consumes: `history.HistoryContext` from Task 3.
- Produces: `telegram_bot.format_context_line(ctx) -> str` (empty string for `None`); `format_azul_alert(flight, comparison, context=None)`, `format_price_alert(flight, max_price, context=None)`, `send_azul_alert(flight, comparison, topic_id=None, context=None)`, `send_price_alert(flight, max_price, topic_id=None, context=None)`. Round-trip functions unchanged.

- [ ] **Step 1: Write the failing tests** — create `tests/test_telegram_context.py`:

```python
from datetime import date

import telegram_bot
from airlines.base import Flight
from alerts import AzulComparison
from history import HistoryContext


def _flight(price=289.0):
    return Flight("CNF", "GIG", "Azul", date(2026, 11, 20), "07h40", "08h50", price, True, 0, "https://x")


def test_below_the_median_and_lowest_since():
    ctx = HistoryContext(-38, 60, True, "2026-08-20", "data")
    assert telegram_bot.format_context_line(ctx) == \
        "📉 38% abaixo da média de 60 dias · menor preço desde 20/08\n"


def test_below_the_median_without_being_the_low():
    assert telegram_bot.format_context_line(HistoryContext(-12, 60, False, "2026-08-20", "data")) == \
        "📉 12% abaixo da média de 60 dias\n"


def test_above_the_median():
    assert telegram_bot.format_context_line(HistoryContext(12, 60, False, None, "data")) == \
        "📈 12% acima da média de 60 dias\n"


def test_within_three_percent_is_flat():
    for pct in (-3, 0, 3):
        assert telegram_bot.format_context_line(HistoryContext(pct, 60, False, None, "data")) == \
            "➖ na média de 60 dias\n"


def test_route_scope_names_the_route():
    assert telegram_bot.format_context_line(HistoryContext(-20, 60, False, None, "rota")) == \
        "📉 20% abaixo da média da rota\n"


def test_no_context_no_line():
    assert telegram_bot.format_context_line(None) == ""


def test_messages_are_byte_identical_without_context_and_gain_one_line_with_it():
    comp = AzulComparison("LATAM", 396.0, 107.0)
    ctx = HistoryContext(-38, 60, True, "2026-08-20", "data")
    plain = telegram_bot.format_azul_alert(_flight(), comp)
    rich = telegram_bot.format_azul_alert(_flight(), comp, ctx)
    assert "média" not in plain
    assert rich.count("\n") == plain.count("\n") + 1
    assert "📉 38% abaixo da média de 60 dias · menor preço desde 20/08" in rich

    plain_p = telegram_bot.format_price_alert(_flight(), 400.0)
    rich_p = telegram_bot.format_price_alert(_flight(), 400.0, ctx)
    assert rich_p.count("\n") == plain_p.count("\n") + 1
```

- [ ] **Step 2: Run to verify they fail**

Run: `timeout 100 python -m pytest tests/test_telegram_context.py -q`
Expected: FAIL with `AttributeError: module 'telegram_bot' has no attribute 'format_context_line'`.

- [ ] **Step 3: Implement** — in `telegram_bot.py`:

Add the import `from history import HistoryContext` and, above `format_azul_alert`:

```python
FLAT_PCT = 3    # same noise threshold the panel uses


def format_context_line(ctx: HistoryContext | None) -> str:
    """One line placing the fare against its own history; empty when there is none."""
    if ctx is None:
        return ""
    base = "da média da rota" if ctx.scope == "rota" else f"da média de {ctx.window_days} dias"
    if abs(ctx.delta_pct) <= FLAT_PCT:
        line = "➖ na média da rota" if ctx.scope == "rota" else f"➖ na média de {ctx.window_days} dias"
    elif ctx.delta_pct < 0:
        line = f"📉 {abs(ctx.delta_pct)}% abaixo {base}"
    else:
        line = f"📈 {ctx.delta_pct}% acima {base}"
    if ctx.is_lowest and ctx.since:
        _y, m, d = ctx.since.split("-")
        line += f" · menor preço desde {d}/{m}"
    return line + "\n"
```

In `format_azul_alert` add the parameter `context: HistoryContext | None = None` and insert `f"{format_context_line(context)}"` on its own line right after the `📊 vs ...` line (the literal that ends with `economia de {...}\n`). In `format_price_alert` add the same parameter and insert it right after the `🎯 abaixo do seu limite ...\n` line. In `send_azul_alert` and `send_price_alert` add `context: HistoryContext | None = None` as the last parameter and pass it to the formatter: `format_azul_alert(flight, comparison, context)` / `format_price_alert(flight, max_price, context)`.

- [ ] **Step 4: Run**

Run: `timeout 100 python -m pytest tests/test_telegram_context.py tests/test_telegram_bot.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add telegram_bot.py tests/test_telegram_context.py
git commit -m "feat(telegram): optional history context line on Azul and price alerts"
```

---

### Task 8: Cycle wiring

**Files:**
- Modify: `cycle.py`, `tests/conftest.py`, `tests/test_cycle.py` (fake sender signatures)
- Test: `tests/test_cycle_history.py`

**Interfaces:**
- Consumes: `history.rollup_closed`, `history.stats`, `history.route_stats`, `history.all_series`, `history.context_for`, `panel.enrich_with_history(deals, stats, route_stats)`, `panel.build_history_payload`, `panel.write_history`, sender `context=` kwarg.
- Produces: `cycle.HISTORY_PATH = "history.json"`.

- [ ] **Step 1: Make the fakes accept the new kwarg** — in `tests/test_cycle.py` every fake sender is declared as `async def fake_send(flight, comparison, topic_id=None):`, `async def fake_azul(flight, comparison, topic_id=None):` or `async def fake_price(flight, max_price, topic_id=None):`. Change each `topic_id=None):` on those lines to `topic_id=None, context=None):`. (Seven definitions: `fake_send` ×3, `fake_price` ×3, `fake_azul` ×1. Find them with `grep -n "topic_id=None):" tests/test_cycle.py`; `fake_search_dates` is not touched.) `tests/test_cycle_roundtrip.py` needs no change: round-trip senders get no context.

In `tests/conftest.py` extend the last fixture:

```python
@pytest.fixture(autouse=True)
def use_tmp_deals_path(tmp_path, monkeypatch):
    """Keep cycle runs from overwriting the real deals.json / history.json in the repo root."""
    import cycle as cycle_module
    monkeypatch.setattr(cycle_module, "DEALS_PATH", str(tmp_path / "deals.json"))
    monkeypatch.setattr(cycle_module, "HISTORY_PATH", str(tmp_path / "history.json"), raising=False)
```

- [ ] **Step 2: Write the failing tests** — append to `tests/test_cycle_history.py`:

```python
async def _seed_two_days(dep):
    await history.init_db()
    for days_ago, price in ((3, 500.0), (2, 400.0)):
        await history.record(
            [{"origem": "CNF", "destino": "GIG", "data": dep, "preco": price}],
            seen_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        )


async def test_alerts_receive_context_computed_before_todays_price_is_recorded(monkeypatch, tmp_path):
    import telegram_bot
    await _silence_telegram(monkeypatch)
    dep = (date.today() + timedelta(days=40)).isoformat()
    await _seed_two_days(dep)
    _only_gig(_canned(price=300.0), monkeypatch)

    seen = []

    async def capture(flight, comparison, topic_id=None, context=None):
        seen.append(context)
        return True

    monkeypatch.setattr(telegram_bot, "send_azul_alert", capture)
    await cycle.run_azul_cycle()

    ctx = seen[0]
    # median of (500, 400) = 450; today's 300 must not be part of its own baseline
    assert (ctx.delta_pct, ctx.is_lowest, ctx.scope) == (-33, True, "data")


async def test_cycle_writes_the_history_file_for_the_panel(monkeypatch, tmp_path):
    await _silence_telegram(monkeypatch)
    dep = (date.today() + timedelta(days=40)).isoformat()
    await _seed_two_days(dep)
    _only_gig(_canned(price=300.0), monkeypatch)
    hist_path = tmp_path / "h.json"
    monkeypatch.setattr(cycle, "HISTORY_PATH", str(hist_path))

    await cycle.run_azul_cycle()

    payload = json.load(open(hist_path, encoding="utf-8"))
    assert [p for _d, p in payload["series"][f"CNF|GIG|{dep}"]] == [500.0, 400.0, 300.0]
    assert "CNF|GIG" in payload["rotas"]


async def test_cycle_rolls_departed_flights_up_before_reading_stats(monkeypatch, tmp_path):
    await _silence_telegram(monkeypatch)
    await history.init_db()
    gone = (date.today() - timedelta(days=2)).isoformat()
    await history.record([{"origem": "CNF", "destino": "GIG", "data": gone, "preco": 250.0}],
                         seen_at=datetime.now(timezone.utc) - timedelta(days=10))
    _only_gig(_canned(price=300.0), monkeypatch)

    await cycle.run_azul_cycle()

    assert f"CNF|GIG|{gone}" not in await history.all_series()
    assert (await history.route_stats())["CNF|GIG"]["n_closed"] == 1
```

- [ ] **Step 3: Run to verify they fail**

Run: `timeout 100 python -m pytest tests/test_cycle_history.py -q`
Expected: the three new tests FAIL (`context` is `None`; `h.json` missing).

- [ ] **Step 4: Implement** — in `cycle.py`:

Below `DEALS_PATH`: `HISTORY_PATH = "history.json"`.

At the top of `run_azul_cycle`, replace the `purge`/`init` lines with:

```python
    today = date.today()
    await cache.purge_expired()
    await history.init_db()
    await history.rollup_closed(today)
    # Read once, before anything is recorded: today's prices must not skew the baseline
    # they are compared against, and every alert below shares the same picture.
    stats = await history.stats()
    route_stats = await history.route_stats()
```

In the Azul loop pass the context:

```python
        for alert in azul_alerts:
            if not await cache.is_cached(alert.flight):
                ctx = history.context_for(alert.flight, stats, route_stats)
                if await telegram_bot.send_azul_alert(
                    alert.flight, alert.comparison, route.topic_id, context=ctx
                ):
```

and in the price-watch loop:

```python
            if not await cache.is_cached(pa.flight, kind="price"):
                ctx = history.context_for(pa.flight, stats, route_stats)
                if await telegram_bot.send_price_alert(
                    pa.flight, pa.max_price, route.topic_id, context=ctx
                ):
```

Replace the enrich/record/write block at the end with:

```python
    enriched = panel.enrich_with_history(all_deals, stats, route_stats)
    await history.record(all_deals)

    panel.write_deals(all_deals, DEALS_PATH)
    try:
        # Re-read after recording so the charts end on today's point.
        panel.write_history(
            panel.build_history_payload(await history.route_stats(), await history.all_series()),
            HISTORY_PATH,
        )
    except Exception as e:
        logger.error(f"histórico do painel não gravado: {e}")
```

Keep the three `logger.info` lines that follow.

- [ ] **Step 5: Run the whole suite**

Run: `timeout 100 python -m pytest -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add cycle.py tests/conftest.py tests/test_cycle.py tests/test_cycle_history.py
git commit -m "feat(cycle): load history once up front, pass context to alerts, write history.json"
```

---

### Task 9: Shared decrypt-and-inflate in both panels

**Files:**
- Modify: `web/switch.js`, `web/app.js`, `web/classic/app.js`

**Interfaces:**
- Produces: global `PanelCrypto.load(url, password) -> Promise<object>`; rejects on wrong password or network error. Handles `v: 1` and `v: 2`.

- [ ] **Step 1: Add `PanelCrypto` to `web/switch.js`** — append at the end of the file:

```js
/* Fetch + decrypt (+ inflate) one encrypted JSON file. Shared by both panels.
   v1 payloads hold the JSON itself; v2 payloads hold gzip(JSON) and say enc:"gzip". */
const PanelCrypto = (() => {
  const b64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));

  async function deriveKey(password, salt, iterations) {
    const base = await crypto.subtle.importKey("raw", new TextEncoder().encode(password), "PBKDF2", false, ["deriveKey"]);
    return crypto.subtle.deriveKey(
      { name: "PBKDF2", salt, iterations, hash: "SHA-256" },
      base, { name: "AES-GCM", length: 256 }, false, ["decrypt"]
    );
  }

  async function inflate(buffer) {
    const stream = new Blob([buffer]).stream().pipeThrough(new DecompressionStream("gzip"));
    return new Response(stream).arrayBuffer();
  }

  return {
    async load(url, password) {
      const res = await fetch(url, { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const p = await res.json();
      const key = await deriveKey(password, b64(p.salt), p.iterations);
      let clear = await crypto.subtle.decrypt({ name: "AES-GCM", iv: b64(p.iv) }, key, b64(p.ciphertext));
      if (p.enc === "gzip") clear = await inflate(clear);
      return JSON.parse(new TextDecoder().decode(clear));
    },
  };
})();
```

- [ ] **Step 2: Use it in the new panel** — in `web/app.js` delete the `b64` constant, the whole `deriveKey` function and the whole `loadDeals` function (the block under `/* ---------------- Decryption ---------------- */`), and replace them with:

```js
/* ---------------- Decryption (shared, see switch.js) ---------------- */
let PASSWORD = "";
const loadDeals = (password) => PanelCrypto.load("deals.enc.json", password);
```

In `unlock`, replace `setup(await loadDeals($("password").value));` with:

```js
    const password = $("password").value;
    const data = await loadDeals(password);
    PASSWORD = password;          // kept in memory only, to fetch history.enc.json later
    setup(data);
```

- [ ] **Step 3: Use it in the classic panel** — in `web/classic/app.js` delete its `deriveKey` function and replace the body of `loadDeals` so the block reads:

```js
/* ---------------- Decryption (shared, see ../switch.js) ---------------- */
// The classic panel lives in /classic/ and reads the same snapshot as the new one.
const loadDeals = (password) => PanelCrypto.load("../deals.enc.json", password);
```

Remove the classic `b64` helper only if `grep -n "b64(" web/classic/app.js` shows no other use.

- [ ] **Step 4: Verify in a browser with both payload versions**

```bash
node --check web/switch.js && node --check web/app.js && node --check web/classic/app.js
S=_site && rm -rf $S && mkdir -p $S/classic
python - <<'EOF'
import json, sys
sys.path.insert(0, ".")
from scripts.encrypt_deals import encrypt_bytes
import panel
from datetime import date
from airlines.base import Flight
fl = [Flight("CNF", "FLN", "Azul", date(2026, 12, 1), "08h00", "10h00", 300.0, True, 0, "https://example.com"),
      Flight("CNF", "FLN", "GOL",  date(2026, 12, 1), "09h00", "11h00", 380.0, True, 0, "https://example.com")]
panel.write_deals(panel.build_deals(fl, "Sul", []), "_site/deals.json")
raw = open("_site/deals.json", "rb").read()
json.dump(encrypt_bytes(raw, "teste123"), open("_site/deals.enc.json", "w"))
json.dump(encrypt_bytes(raw, "teste123", compress=False), open("_site/deals.v1.json", "w"))
EOF
cp web/index.html web/style.css web/app.js web/switch.js $S/ && cp web/classic/* $S/classic/
python -m http.server 8765 --directory $S
```

Open `http://localhost:8765/`, unlock with `teste123`: the FLN pass must render. Open `/classic/`: it must unlock too. Then `cp $S/deals.v1.json $S/deals.enc.json`, reload both: both must still unlock (v1 path). Wrong password must show "Senha incorreta". Console must be free of errors. Stop the server and `rm -rf _site`.

- [ ] **Step 5: Commit**

```bash
git add web/switch.js web/app.js web/classic/app.js
git commit -m "feat(panel): one shared decrypt routine that also inflates gzip payloads"
```

---

### Task 10: New panel — date chart, route section, "vs. rota"

**Files:**
- Modify: `web/app.js`, `web/style.css`

**Interfaces:**
- Consumes: `PanelCrypto.load`, `PASSWORD` (Task 9); `history.enc.json` shape `{gerado_em, rotas: {"ORIG|DEST": {med, min, n_dates, by_month, by_dow, lead_curve:[{bucket, med, n}], n_closed}}, series: {"ORIG|DEST|DATE": [[dia, price], ...]}}`; deal fields `rota_med`, `rota_min`, `rota_delta_pct`, `hist_dias`.
- Produces: nothing consumed by later tasks.

Before writing chart code, load the `dataviz` skill and follow its colour, axis and accessibility guidance, reusing the panel's existing CSS custom properties from `web/style.css` (do not introduce a new palette).

- [ ] **Step 1: Lazy history loader** — in `web/app.js`, below the `loadDeals` line:

```js
/* History is only needed once a pass is opened: fetch it once, share the promise. */
let HISTORY = null;          // resolved payload, or false when it could not be loaded
let historyPromise = null;
function ensureHistory() {
  if (!historyPromise) {
    historyPromise = PanelCrypto.load("history.enc.json", PASSWORD)
      .then((h) => { HISTORY = h; })
      .catch(() => { HISTORY = false; })
      .then(render);
  }
  return historyPromise;
}
```

In the `$("cards")` click handler inside `setup`, after `OPEN.has(key) ? OPEN.delete(key) : OPEN.add(key);` add `if (OPEN.size) ensureHistory();`.

- [ ] **Step 2: Chart and route section** — add to `web/app.js`, above `passHTML`:

```js
const LEAD_LABELS = ["0–7 d", "8–14 d", "15–30 d", "31–60 d", "61–90 d", "91–120 d", "121–180 d"];
const DOW_LABELS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"];   // Python weekday(): Monday = 0
const MIN_CLOSED_DATES = 20, MIN_LEAD_BUCKETS = 4;

/* Daily series of one flight date: line, median rule, floor rule, today's point. */
function dateChart(d) {
  const points = HISTORY.series[`${d.origem}|${d.destino}|${d.data}`];
  if (!points || points.length < 2) return `<p class="hist-note">Ainda sem série suficiente para esta data.</p>`;
  const prices = points.map(([, p]) => p);
  const w = 560, h = 160, padL = 46, padR = 12, padT = 12, padB = 22;
  const lo = Math.min(...prices), hi = Math.max(...prices), span = hi - lo || 1;
  const x = (i) => padL + (i / (points.length - 1)) * (w - padL - padR);
  const y = (v) => padT + (1 - (v - lo) / span) * (h - padT - padB);
  const path = prices.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(" ");
  const med = d.hist_med, rule = (v, cls, label) => (v == null || v < lo || v > hi) ? "" :
    `<line class="${cls}" x1="${padL}" x2="${w - padR}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}"/>
     <text class="rule-label" x="${w - padR}" y="${(y(v) - 4).toFixed(1)}" text-anchor="end">${label} ${fmtBRL(v)}</text>`;
  const last = points.length - 1;
  return `<figure class="hist-chart">
    <figcaption>Preço desta data · ${points.length} dias observados</figcaption>
    <svg viewBox="0 0 ${w} ${h}" role="img"
      aria-label="Preço de ${fmtDate(d.data)} ao longo de ${points.length} dias: de ${fmtBRL(prices[0])} a ${fmtBRL(prices[last])}, mínimo ${fmtBRL(lo)}, máximo ${fmtBRL(hi)}">
      <text class="axis" x="${padL - 6}" y="${y(hi) + 4}" text-anchor="end">${fmtInt(hi)}</text>
      <text class="axis" x="${padL - 6}" y="${y(lo) + 4}" text-anchor="end">${fmtInt(lo)}</text>
      <text class="axis" x="${padL}" y="${h - 4}">${fmtShort(points[0][0])}</text>
      <text class="axis" x="${w - padR}" y="${h - 4}" text-anchor="end">${fmtShort(points[last][0])}</text>
      ${rule(med, "rule-med", "mediana")}
      <path class="series" d="${path}"/>
      <circle class="today" cx="${x(last).toFixed(1)}" cy="${y(prices[last]).toFixed(1)}" r="4"/>
    </svg></figure>`;
}

function barRows(entries, fmtKey) {
  if (!entries.length) return "";
  const max = Math.max(...entries.map(([, v]) => v));
  const min = Math.min(...entries.map(([, v]) => v));
  return entries.map(([k, v]) => `<div class="bar-row${v === min ? " is-low" : ""}">
    <span class="bar-key">${esc(fmtKey(k))}</span>
    <span class="bar-track"><span class="bar-fill" style="width:${Math.round((v / max) * 100)}%"></span></span>
    <span class="bar-val num">${fmtBRL(v)}</span></div>`).join("");
}

/* What the route usually costs, and (once enough flights have departed) when to buy. */
function routeSection(d) {
  const r = HISTORY.rotas[`${d.origem}|${d.destino}`];
  if (!r) return "";
  const months = Object.entries(r.by_month).sort(([a], [b]) => a.localeCompare(b));
  const dows = Object.entries(r.by_dow).sort(([a], [b]) => Number(a) - Number(b));
  const lead = r.lead_curve || [];
  const enough = r.n_closed >= MIN_CLOSED_DATES && lead.length >= MIN_LEAD_BUCKETS;
  return `<section class="hist-route" aria-label="Histórico da rota">
    <h3>Rota ${esc(d.origem)} → ${esc(d.destino)}</h3>
    <p class="hist-facts"><span>Preço típico <b class="num">${fmtBRL(r.med)}</b></span>
      <span>Piso já visto <b class="num">${fmtBRL(r.min)}</b></span>
      <span>${fmtInt(r.n_dates)} datas acompanhadas</span></p>
    <div class="hist-cols">
      <div><h4>Por mês do voo</h4>${barRows(months, (m) => MON[Number(m) - 1])}</div>
      <div><h4>Por dia da semana</h4>${barRows(dows, (k) => DOW_LABELS[Number(k)])}</div>
      <div><h4>Quando comprar</h4>${enough
        ? barRows(lead.map((b) => [b.bucket, b.med]), (k) => LEAD_LABELS[Number(k)])
        : `<p class="hist-note">Coletando dados — disponível após algumas semanas de voos encerrados (${fmtInt(r.n_closed)} de ${MIN_CLOSED_DATES}).</p>`}</div>
    </div></section>`;
}

function historyBlock(g) {
  if (g.rt) return "";
  if (HISTORY === null) return `<p class="hist-note">Carregando histórico…</p>`;
  if (HISTORY === false) return `<p class="hist-note">Histórico indisponível agora. Calendário e tabela seguem funcionando.</p>`;
  return dateChart(g.best) + routeSection(g.best);
}
```

In `passHTML`, change the open-body line to:

```js
    ${open ? `<div class="pass-body">${g.rt ? roundTripBody(d) : historyBlock(g) + calendar(g) + datesTable(g)}</div>` : ""}
```

- [ ] **Step 3: "vs. rota" in the table** — in `tableRowHTML`, after the `vs. média` cell add:

```js
    ${cell("vs. rota", d.rota_delta_pct == null ? '<span class="muted">—</span>'
      : `<span class="delta ${d.rota_delta_pct < -3 ? "down" : d.rota_delta_pct > 3 ? "up" : "flat"}" title="Preço típico da rota: ${fmtBRL(d.rota_med)}">${d.rota_delta_pct > 0 ? "+" : ""}${d.rota_delta_pct}%</span>`)}
```

In `web/index.html`, in the table head, after the `vs. média` `<th>` add:

```html
                <th data-sort="rota_delta_pct" aria-sort="none"><button type="button">vs. rota</button></th>
```

In `passHTML`, replace the `sem histórico` fallback so a never-seen date still shows a verdict:

```js
        ${delta(d) || (g.rt ? "" : d.rota_delta_pct != null
          ? `<span class="delta ${d.rota_delta_pct < -3 ? "down" : d.rota_delta_pct > 3 ? "up" : "flat"}" title="Comparado ao preço típico da rota, ${fmtBRL(d.rota_med)}">${Math.abs(d.rota_delta_pct)}% ${d.rota_delta_pct < 0 ? "abaixo" : "acima"} da rota</span>`
          : '<span class="delta flat">sem histórico</span>')}
```

- [ ] **Step 4: Styles** — append to `web/style.css` (every colour is an existing `:root` token of that file: `--text-2`, `--text-3`, `--amber`, `--green`, `--line`, `--cream`):

```css
/* ---------- History: date chart + route summary ---------- */
.hist-chart { margin: 0 0 1.25rem; }
.hist-chart figcaption, .hist-route h4 { font-size: .72rem; letter-spacing: .08em; text-transform: uppercase; color: var(--text-3); margin-bottom: .4rem; }
.hist-chart svg { width: 100%; height: auto; display: block; }
.hist-chart .series { fill: none; stroke: var(--amber); stroke-width: 2; stroke-linejoin: round; }
.hist-chart .today { fill: var(--amber); }
.hist-chart .rule-med { stroke: var(--text-3); stroke-dasharray: 4 4; stroke-width: 1; }
.hist-chart .axis, .hist-chart .rule-label { fill: var(--text-3); font-size: 10px; font-family: inherit; }
.hist-route { margin-bottom: 1.25rem; }
.hist-route h3 { font-size: .95rem; margin: 0 0 .35rem; }
.hist-facts { display: flex; flex-wrap: wrap; gap: .35rem 1.25rem; margin: 0 0 .9rem; color: var(--text-3); font-size: .85rem; }
.hist-facts b { color: var(--cream); font-weight: 600; }
.hist-cols { display: grid; grid-template-columns: repeat(auto-fit, minmax(13rem, 1fr)); gap: 1rem 1.5rem; }
.bar-row { display: grid; grid-template-columns: 4.2rem 1fr auto; align-items: center; gap: .5rem; font-size: .8rem; padding: .12rem 0; }
.bar-track { height: .45rem; border-radius: 99px; background: var(--line); overflow: hidden; }
.bar-fill { display: block; height: 100%; background: var(--text-2); border-radius: inherit; }
.bar-row.is-low .bar-fill { background: var(--green); }
.bar-row.is-low .bar-val { color: var(--green); }
.hist-note { color: var(--text-3); font-size: .85rem; margin: 0 0 1rem; }
```

- [ ] **Step 5: Verify in a browser** — build a fixture that has history, then look at it:

```bash
S=_site && rm -rf $S && mkdir -p $S/classic
python - <<'EOF'
import asyncio, json, random, sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0, ".")
import history, panel, config
from airlines.base import Flight
from scripts.encrypt_deals import encrypt_file
history.DB_PATH = Path("_site/h.db")
random.seed(3)

async def main():
    await history.init_db()
    today = date.today()
    async def day(n_ago):
        deals = []
        for ap in ("FLN", "POA", "LIS"):
            base = 2400 if ap == "LIS" else 350
            for n in range(-60, 70, 5):     # past flight dates become closed_dates
                deals.append({"origem": "CNF", "destino": ap, "data": (today + timedelta(days=n)).isoformat(),
                              "preco": float(base + random.randint(-90, 160))})
        await history.record(deals, seen_at=datetime.now(timezone.utc) - timedelta(days=n_ago))
    for n_ago in range(75, 0, -1):
        await day(n_ago)
    await history.rollup_closed(today)
    stats, routes = await history.stats(), await history.route_stats()
    flights = [Flight("CNF", ap, "Azul", today + timedelta(days=n), "08h00", "10h00",
                      float((2400 if ap == "LIS" else 350) - 40), True, 0, "https://example.com")
               for ap in ("FLN", "POA", "LIS") for n in range(30, 70, 5)]
    deals = []
    for ap, region in (("FLN", "Sul"), ("POA", "Sul"), ("LIS", "Portugal")):
        deals += panel.build_deals([f for f in flights if f.destination == ap], region, [])
    panel.enrich_with_history(deals, stats, routes)
    await history.record(deals)
    panel.write_deals(deals, "_site/deals.json")
    panel.write_history(panel.build_history_payload(await history.route_stats(), await history.all_series()),
                        "_site/history.json")
    for name in ("deals", "history"):
        encrypt_file(f"_site/{name}.json", f"_site/{name}.enc.json", "teste123")
asyncio.run(main())
EOF
rm $S/deals.json $S/history.json $S/h.db
cp web/index.html web/style.css web/app.js web/switch.js $S/ && cp web/classic/* $S/classic/
python -m http.server 8765 --directory $S
```

Check, at desktop width and at 375 px:
1. Unlock with `teste123`; open the FLN pass: chart renders with median rule and today's dot; route section shows month bars, weekday bars, and "Coletando dados" or the lead bars depending on `n_closed`.
2. The cheapest bar in each group is highlighted; nothing overflows horizontally (`document.documentElement.scrollWidth <= innerWidth`).
3. Table view shows the "vs. rota" column and sorts by it.
4. Delete `history.enc.json` from `$S`, reload, open a pass: the notice "Histórico indisponível agora" shows and calendar + table still work.
5. `/classic/` still unlocks. Console has no errors. Stop the server and `rm -rf _site`.

- [ ] **Step 6: Commit**

```bash
git add web/app.js web/style.css web/index.html
git commit -m "feat(panel): date price chart, route summary and route-level verdict"
```

---

### Task 11: Workflow — restore, backup, ship `history.enc.json`

**Files:**
- Modify: `.github/workflows/azul-alert.yml`, `.gitignore`

**Interfaces:**
- Consumes: `scripts/history_backup.py` CLI, `scripts/encrypt_deals.py` CLI (encrypts both files).

- [ ] **Step 1: Edit the workflow**

`permissions.contents`: `read` → `write` (release assets need it).

After the "Restore dedup cache" step add:

```yaml
      - name: Restore history from release when the cache is cold
        if: hashFiles('data/cache.db') == ''
        env:
          PANEL_PASSWORD: ${{ secrets.PANEL_PASSWORD }}
          GH_TOKEN: ${{ github.token }}
        run: python scripts/history_backup.py restore
```

After "Run one pass" add (default `if: success()` means an empty or failed cycle never overwrites a good backup):

```yaml
      - name: Back up history to the release
        continue-on-error: true
        env:
          PANEL_PASSWORD: ${{ secrets.PANEL_PASSWORD }}
          GH_TOKEN: ${{ github.token }}
        run: python scripts/history_backup.py backup
```

Rename "Encrypt deals snapshot" to "Encrypt deals and history" (the command stays `python scripts/encrypt_deals.py`).

In "Assemble site", after `cp deals.enc.json _site/` add:

```yaml
          if [ -f history.enc.json ]; then cp history.enc.json _site/; fi
```

- [ ] **Step 2: Ignore the new generated files** — add to `.gitignore`:

```
history.json
history.enc.json
```

- [ ] **Step 3: Validate**

```bash
python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/azul-alert.yml')); print('yaml ok')"
timeout 100 python -m pytest -q
```

Expected: `yaml ok` (install `pyyaml` locally if missing; it is not a project dependency) and the full suite PASS.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/azul-alert.yml .gitignore
git commit -m "ci: restore history from the release on a cold cache, back it up after each cycle"
```

---

### Task 12: Rollout (after the owner merges and pushes)

**Files:** none, unless step 4 is taken.

- [ ] **Step 1:** Trigger one run: `gh workflow run azul-alert.yml`, then `gh run watch`.
- [ ] **Step 2:** In the log confirm: no `migração falhou`; `histórico salvo na release history-db`; the cycle summary line; `gh release view history-db` lists `cache.db.gz.enc`.
- [ ] **Step 3:** `curl -sI https://vdto88.github.io/flight-alerts-bot/deals.enc.json` — size should drop from about 4 MB to well under 1 MB; `history.enc.json` returns 200. Unlock the live panel, open a pass, confirm the chart; unlock `/classic/`.
- [ ] **Step 4:** Prove the restore path once: change the cache key prefix in the workflow from `azul-dedup-` to `azul-db-` (both `key` and `restore-keys`), push, trigger a run, and confirm the log shows `histórico restaurado da release history-db` and that the panel still has history afterwards. Keep the new prefix.
- [ ] **Step 5:** Update the project memory note about panel price history: it no longer vanishes with the Actions cache; the durable copy is the `history-db` release.
