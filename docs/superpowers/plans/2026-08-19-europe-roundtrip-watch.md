# Europe Round-Trip Watch — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Alert (Telegram + web panel) whenever a France/Spain/Italy/Portugal round-trip — open-jaw allowed, 13–15 day stay, departing Feb–May 2027 — totals under R$3,000 per person.

**Architecture:** A new `RoundTripWatch` config drives one extra date span (Feb 1–Jun 15 2027) into the existing per-leg Google Flights search. After the normal per-leg cycle collects all European ida/volta legs, a new pure evaluator pairs the cheapest ida on each departure date with the cheapest volta 13–15 days later, emitting one alert per qualifying departure date. Composite-key dedup (24h) prevents re-alerting the same combo; the same qualifying combos are also written into the encrypted panel snapshot as `tipo:"roundtrip"` rows.

**Tech Stack:** Python 3.11, `dataclasses`, `aiosqlite`, `python-telegram-bot`, pytest; vanilla JS for the panel.

## Global Constraints

- Prices are BRL, per person; ignore any leg with `price is None or price <= 0`.
- The 4 countries = 8 airports: `LIS, OPO, MAD, BCN, FCO, MXP, CDG, ORY`.
- Depart window: `2027-02-01`..`2027-05-31` (inclusive). Stay: 13–15 days (never > 15). Volta therefore falls `2027-02-14`..`2027-06-15`.
- Threshold: `ida.price + volta.price <= 3000.0` fires.
- Telegram topic: General (`topic_id = None`).
- Dedup TTL: `CACHE_TTL_HOURS` (24h), same table `seen_flights`.
- Follow existing patterns: pure evaluators in `alerts.py`, I/O senders in `telegram_bot.py` returning `bool` with topic→General retry, panel dicts in `panel.py`.
- Run tests with `python -m pytest <path> -v` from the repo root.

---

### Task 1: `RoundTripWatch` config

**Files:**
- Modify: `config.py` (add dataclass after `PriceWatch`, add `ROUND_TRIP_WATCHES` after `PRICE_WATCHES`)
- Test: `tests/test_round_trip_watches.py` (new)

**Interfaces:**
- Produces: `config.RoundTripWatch(name:str, airports:tuple[str,...], depart_window:SearchWindow, stay_min:int, stay_max:int, max_total:float, topic_id:int|None)` and `config.ROUND_TRIP_WATCHES: list[RoundTripWatch]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_round_trip_watches.py
from datetime import date
import config


def test_round_trip_watch_fields():
    w = config.RoundTripWatch(
        name="Europa",
        airports=("LIS", "OPO", "MAD", "BCN", "FCO", "MXP", "CDG", "ORY"),
        depart_window=config.SearchWindow(date(2027, 2, 1), date(2027, 5, 31)),
        stay_min=13, stay_max=15, max_total=3000.0, topic_id=None,
    )
    assert w.stay_min == 13 and w.stay_max == 15
    assert w.max_total == 3000.0
    assert w.topic_id is None


def test_europe_watch_is_seeded():
    by_name = {w.name: w for w in config.ROUND_TRIP_WATCHES}
    assert "Europa" in by_name
    w = by_name["Europa"]
    assert set(w.airports) == {"LIS", "OPO", "MAD", "BCN", "FCO", "MXP", "CDG", "ORY"}
    assert w.depart_window == config.SearchWindow(date(2027, 2, 1), date(2027, 5, 31))
    assert (w.stay_min, w.stay_max) == (13, 15)
    assert w.max_total == 3000.0
    assert w.topic_id is None


def test_watch_airports_all_belong_to_a_group():
    group_airports = {a for g in config.GROUPS for a in g.airports}
    for w in config.ROUND_TRIP_WATCHES:
        for a in w.airports:
            assert a in group_airports, f"{a} watched but in no Group"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_round_trip_watches.py -v`
Expected: FAIL with `AttributeError: module 'config' has no attribute 'RoundTripWatch'`

- [ ] **Step 3: Write minimal implementation**

In `config.py`, after the `PriceWatch` dataclass (around line 41):

```python
@dataclass(frozen=True)
class RoundTripWatch:
    name: str                    # display/topic label, e.g. "Europa"
    airports: tuple[str, ...]    # pool: ida-destination and volta-origin
    depart_window: SearchWindow  # allowed ida departure dates
    stay_min: int                # min stay in days
    stay_max: int                # max stay in days (never exceeded)
    max_total: float             # BRL; alert when ida+volta <= this
    topic_id: int | None         # Telegram topic; None = General
```

After the `PRICE_WATCHES` list (around line 70):

```python
ROUND_TRIP_WATCHES: list[RoundTripWatch] = [
    RoundTripWatch(
        name="Europa",
        airports=("LIS", "OPO", "MAD", "BCN", "FCO", "MXP", "CDG", "ORY"),
        depart_window=SearchWindow(date(2027, 2, 1), date(2027, 5, 31)),
        stay_min=13, stay_max=15,
        max_total=3000.0,
        topic_id=None,   # General
    ),
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_round_trip_watches.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_round_trip_watches.py
git commit -m "feat(config): RoundTripWatch + Europe watch seed"
```

---

### Task 2: `target_dates` unions round-trip watch spans

**Files:**
- Modify: `routing.py:42-54` (`target_dates`)
- Test: `tests/test_config_groups.py` (append) — or `tests/test_round_trip_watches.py`; use the latter to keep round-trip tests together.

**Interfaces:**
- Consumes: `config.RoundTripWatch`, `config.SearchWindow`.
- Produces: `routing.target_dates(airport, today, groups, win_min, win_max, watches=(), rt_watches=()) -> list[date]` — for any airport in an rt watch, the returned set also covers `[depart_window.start, depart_window.end + stay_max]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_round_trip_watches.py  (append)
from datetime import date, timedelta
import routing, config


def _europe_watch():
    return config.RoundTripWatch(
        name="Europa", airports=("CDG",),
        depart_window=config.SearchWindow(date(2027, 2, 1), date(2027, 5, 31)),
        stay_min=13, stay_max=15, max_total=3000.0, topic_id=None,
    )


def test_target_dates_covers_rt_span_for_pool_airport():
    today = date(2026, 8, 19)
    dates = routing.target_dates(
        "CDG", today, config.GROUPS, 30, 120, (), (_europe_watch(),)
    )
    assert date(2027, 2, 1) in dates           # depart window start
    assert date(2027, 5, 31) in dates          # depart window end
    assert date(2027, 6, 15) in dates          # end + stay_max (May 31 + 15)
    assert date(2027, 1, 31) not in dates       # just before window
    assert date(2027, 6, 16) not in dates       # just after end+stay_max


def test_target_dates_ignores_rt_span_for_non_pool_airport():
    today = date(2026, 8, 19)
    dates = routing.target_dates(
        "SLZ", today, config.GROUPS, 30, 120, (), (_europe_watch(),)
    )
    assert date(2027, 2, 1) not in dates
    assert date(2027, 6, 15) not in dates
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_round_trip_watches.py -k target_dates -v`
Expected: FAIL with `TypeError: target_dates() takes ... positional arguments but 7 were given`

- [ ] **Step 3: Write minimal implementation**

Replace `target_dates` in `routing.py`:

```python
def target_dates(airport: str, today: date, groups: list[Group],
                 win_min: int, win_max: int, watches=(), rt_watches=()) -> list[date]:
    """Rolling window (today+win_min .. today+win_max) UNION the airport's group windows
    UNION any PriceWatch window for the airport UNION any RoundTripWatch span
    (depart_window.start .. depart_window.end + stay_max) when the airport is in that
    watch's pool. Deduped, sorted, past dropped."""
    dates: set[date] = {today + timedelta(days=n) for n in range(win_min, win_max + 1)}
    g = group_of(airport, groups)
    if g:
        for w in g.windows:
            dates.update(_window_dates(w.start, w.end))
    for pw in watches:
        if pw.airport == airport and pw.window is not None:
            dates.update(_window_dates(pw.window.start, pw.window.end))
    for rw in rt_watches:
        if airport in rw.airports:
            dates.update(_window_dates(
                rw.depart_window.start,
                rw.depart_window.end + timedelta(days=rw.stay_max),
            ))
    return sorted(d for d in dates if d >= today)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_round_trip_watches.py -k target_dates -v`
Then the full routing suite (no regressions): `python -m pytest tests/test_config_groups.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add routing.py tests/test_round_trip_watches.py
git commit -m "feat(routing): target_dates unions round-trip watch span"
```

---

### Task 3: `evaluate_round_trip` evaluator

**Files:**
- Modify: `alerts.py` (append `RoundTripAlert`, `evaluate_round_trip`, `round_trip_cache_key`; add `from datetime import timedelta` and `import math` at top)
- Test: `tests/test_round_trip_eval.py` (new)

**Interfaces:**
- Consumes: `airlines.base.Flight`, `config.RoundTripWatch`.
- Produces:
  - `alerts.RoundTripAlert(watch_name:str, ida:Flight, volta:Flight, stay_days:int, total:float, max_total:float)`
  - `alerts.evaluate_round_trip(ida_legs:list[Flight], volta_legs:list[Flight], watch:RoundTripWatch) -> list[RoundTripAlert]` — one alert per qualifying ida departure date; picks the cheapest open-jaw combo and the stay in `[stay_min, stay_max]` that minimizes the total; emits only when `total <= max_total`.
  - `alerts.round_trip_cache_key(rt:RoundTripAlert) -> str`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_round_trip_eval.py
from datetime import date
import config
from airlines.base import Flight
from alerts import evaluate_round_trip, round_trip_cache_key


def leg(origin, dest, d, price, airline="AZUL"):
    return Flight(
        origin=origin, destination=dest, airline=airline,
        departure_date=d, departure_time="10h00", arrival_time="20h00",
        price=price, is_direct=False, stops=1,
        booking_url=f"http://x/{origin}{dest}/{d}",
    )


WATCH = config.RoundTripWatch(
    name="Europa", airports=("CDG", "MXP", "LIS"),
    depart_window=config.SearchWindow(date(2027, 3, 1), date(2027, 3, 31)),
    stay_min=13, stay_max=15, max_total=3000.0, topic_id=None,
)


def test_pairs_open_jaw_cheapest_under_threshold():
    ida = [leg("CNF", "CDG", date(2027, 3, 1), 1500.0, "AZUL"),
           leg("CNF", "MXP", date(2027, 3, 1), 1400.0, "LATAM")]   # cheaper ida = MXP
    volta = [leg("CDG", "CNF", date(2027, 3, 15), 1450.0, "AZUL"),  # +14 days
             leg("LIS", "CNF", date(2027, 3, 15), 1400.0, "TAP")]   # cheaper volta = LIS
    out = evaluate_round_trip(ida, volta, WATCH)
    assert len(out) == 1
    rt = out[0]
    assert rt.ida.destination == "MXP" and rt.volta.origin == "LIS"  # open-jaw min+min
    assert rt.stay_days == 14
    assert rt.total == 2800.0


def test_rejects_stay_outside_13_15():
    ida = [leg("CNF", "CDG", date(2027, 3, 1), 1000.0)]
    volta_12 = [leg("CDG", "CNF", date(2027, 3, 13), 1000.0)]   # 12 days
    volta_16 = [leg("CDG", "CNF", date(2027, 3, 17), 1000.0)]   # 16 days
    assert evaluate_round_trip(ida, volta_12, WATCH) == []
    assert evaluate_round_trip(ida, volta_16, WATCH) == []


def test_picks_stay_that_minimizes_total():
    ida = [leg("CNF", "CDG", date(2027, 3, 1), 1000.0)]
    volta = [leg("CDG", "CNF", date(2027, 3, 14), 1900.0),   # +13, total 2900
             leg("CDG", "CNF", date(2027, 3, 15), 1500.0),   # +14, total 2500 (best)
             leg("CDG", "CNF", date(2027, 3, 16), 1800.0)]   # +15, total 2800
    out = evaluate_round_trip(ida, volta, WATCH)
    assert len(out) == 1 and out[0].total == 2500.0 and out[0].stay_days == 14


def test_not_fired_above_threshold_fired_at_exact_limit():
    ida = [leg("CNF", "CDG", date(2027, 3, 1), 1500.0)]
    over = [leg("CDG", "CNF", date(2027, 3, 15), 1500.01)]
    exact = [leg("CDG", "CNF", date(2027, 3, 15), 1500.0)]
    assert evaluate_round_trip(ida, over, WATCH) == []
    assert len(evaluate_round_trip(ida, exact, WATCH)) == 1  # total 3000.0 == max


def test_one_alert_per_departure_date():
    ida = [leg("CNF", "CDG", date(2027, 3, 1), 1000.0),
           leg("CNF", "CDG", date(2027, 3, 2), 1000.0)]
    volta = [leg("CDG", "CNF", date(2027, 3, 15), 1000.0),   # pairs with Mar 1 (+14)
             leg("CDG", "CNF", date(2027, 3, 16), 1000.0)]   # pairs with Mar 2 (+14)
    out = evaluate_round_trip(ida, volta, WATCH)
    assert {rt.ida.departure_date for rt in out} == {date(2027, 3, 1), date(2027, 3, 2)}


def test_ignores_nonpositive_prices_and_out_of_window_ida():
    ida = [leg("CNF", "CDG", date(2027, 3, 1), 0.0),           # price<=0 ignored
           leg("CNF", "CDG", date(2027, 2, 1), 100.0)]          # before depart_window
    volta = [leg("CDG", "CNF", date(2027, 3, 15), 100.0)]
    assert evaluate_round_trip(ida, volta, WATCH) == []


def test_cache_key_is_stable_and_distinguishes_combos():
    ida = [leg("CNF", "CDG", date(2027, 3, 1), 1500.0)]
    volta = [leg("CDG", "CNF", date(2027, 3, 15), 1450.0)]
    rt = evaluate_round_trip(ida, volta, WATCH)[0]
    k = round_trip_cache_key(rt)
    assert k == round_trip_cache_key(rt)          # stable
    assert k.startswith("rt:Europa|CNF-CDG|2027-03-01|CDG-CNF|2027-03-15|")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_round_trip_eval.py -v`
Expected: FAIL with `ImportError: cannot import name 'evaluate_round_trip'`

- [ ] **Step 3: Write minimal implementation**

At the top of `alerts.py`, extend imports:

```python
import math
from datetime import timedelta
```

At the end of `alerts.py`:

```python
from config import RoundTripWatch


@dataclass
class RoundTripAlert:
    watch_name: str
    ida: Flight
    volta: Flight
    stay_days: int
    total: float
    max_total: float


def _cheapest_by_date(legs: list[Flight], lo=None, hi=None) -> dict:
    """Map departure_date -> cheapest Flight on that date (price > 0), optionally
    restricted to [lo, hi]."""
    out: dict = {}
    for f in legs:
        if f.price is None or f.price <= 0:
            continue
        d = f.departure_date
        if (lo is not None and d < lo) or (hi is not None and d > hi):
            continue
        if d not in out or f.price < out[d].price:
            out[d] = f
    return out


def evaluate_round_trip(ida_legs: list[Flight], volta_legs: list[Flight],
                        watch: RoundTripWatch) -> list[RoundTripAlert]:
    """One alert per ida departure date inside watch.depart_window whose cheapest
    open-jaw round-trip (cheapest ida that day + cheapest volta stay_min..stay_max
    days later) totals <= watch.max_total."""
    w = watch
    ida_by_date = _cheapest_by_date(ida_legs, w.depart_window.start, w.depart_window.end)
    volta_by_date = _cheapest_by_date(volta_legs)

    alerts: list[RoundTripAlert] = []
    for d in sorted(ida_by_date):
        best = None  # (total, volta_flight, stay_days)
        for s in range(w.stay_min, w.stay_max + 1):
            volta = volta_by_date.get(d + timedelta(days=s))
            if volta is None:
                continue
            total = ida_by_date[d].price + volta.price
            if best is None or total < best[0]:
                best = (total, volta, s)
        if best is None or best[0] > w.max_total:
            continue
        total, volta, s = best
        alerts.append(RoundTripAlert(
            watch_name=w.name, ida=ida_by_date[d], volta=volta,
            stay_days=s, total=round(total, 2), max_total=w.max_total,
        ))
    return alerts


def round_trip_cache_key(rt: RoundTripAlert) -> str:
    total_floor = math.floor(rt.total / 10) * 10
    return (f"rt:{rt.watch_name}|{rt.ida.origin}-{rt.ida.destination}|{rt.ida.departure_date}"
            f"|{rt.volta.origin}-{rt.volta.destination}|{rt.volta.departure_date}|{total_floor}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_round_trip_eval.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add alerts.py tests/test_round_trip_eval.py
git commit -m "feat(alerts): evaluate_round_trip + composite cache key"
```

---

### Task 4: composite-key cache helpers

**Files:**
- Modify: `cache.py` (append `is_key_cached`, `save_key`)
- Test: `tests/test_cache_keys.py` (new)

**Interfaces:**
- Produces: `cache.is_key_cached(key:str) -> bool`, `cache.save_key(key:str, ttl_hours:int=24) -> None`. Same `seen_flights` table as `is_cached`/`save_to_cache`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cache_keys.py
import asyncio
from pathlib import Path
import cache


def test_save_and_read_raw_key(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "DB_PATH", Path(tmp_path) / "cache.db")

    async def scenario():
        await cache.init_db()
        assert await cache.is_key_cached("rt:Europa|x") is False
        await cache.save_key("rt:Europa|x", ttl_hours=24)
        assert await cache.is_key_cached("rt:Europa|x") is True
        assert await cache.is_key_cached("rt:Europa|y") is False

    asyncio.run(scenario())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cache_keys.py -v`
Expected: FAIL with `AttributeError: module 'cache' has no attribute 'is_key_cached'`

- [ ] **Step 3: Write minimal implementation**

Append to `cache.py`:

```python
async def is_key_cached(key: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM seen_flights WHERE cache_key = ? AND expires_at > ?",
            (key, _now_iso()),
        ) as cursor:
            return await cursor.fetchone() is not None


async def save_key(key: str, ttl_hours: int = 24) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO seen_flights (cache_key, detected_at, expires_at) VALUES (?, ?, ?)",
            (key, _now_iso(), _expires_iso(ttl_hours)),
        )
        await db.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cache_keys.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add cache.py tests/test_cache_keys.py
git commit -m "feat(cache): raw composite-key dedup helpers"
```

---

### Task 5: panel round-trip deals

**Files:**
- Modify: `panel.py` (add `build_round_trip_deals`; add `from alerts import RoundTripAlert`)
- Test: `tests/test_panel_roundtrip.py` (new)

**Interfaces:**
- Consumes: `alerts.RoundTripAlert`.
- Produces: `panel.build_round_trip_deals(rt_alerts:list[RoundTripAlert], region:str) -> list[dict]` — one `tipo:"roundtrip"` dict per alert with the fields listed in the spec.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_panel_roundtrip.py
from datetime import date
import panel
from airlines.base import Flight
from alerts import RoundTripAlert


def _leg(o, d, dt, price, airline, url):
    return Flight(origin=o, destination=d, airline=airline, departure_date=dt,
                  departure_time="10h00", arrival_time="20h00", price=price,
                  is_direct=False, stops=1, booking_url=url)


def test_build_round_trip_deal_shape():
    rt = RoundTripAlert(
        watch_name="Europa",
        ida=_leg("CNF", "CDG", date(2027, 3, 1), 1450.0, "AZUL", "http://ida"),
        volta=_leg("MXP", "CNF", date(2027, 3, 15), 1440.0, "LATAM", "http://volta"),
        stay_days=14, total=2890.0, max_total=3000.0,
    )
    [deal] = panel.build_round_trip_deals([rt], "Europa (ida+volta)")
    assert deal["tipo"] == "roundtrip"
    assert deal["regiao"] == "Europa (ida+volta)"
    assert deal["origem"] == "CNF" and deal["destino"] == "CDG"
    assert deal["data"] == "2027-03-01"
    assert deal["preco"] == 2890.0
    assert deal["url_compra"] == "http://ida"
    assert deal["azul_cheapest"] is False and deal["price_watch"] is None
    assert deal["volta_origem"] == "MXP" and deal["volta_destino"] == "CNF"
    assert deal["data_volta"] == "2027-03-15"
    assert deal["cia_ida"] == "AZUL" and deal["cia_volta"] == "LATAM"
    assert deal["preco_ida"] == 1450.0 and deal["preco_volta"] == 1440.0
    assert deal["url_ida"] == "http://ida" and deal["url_volta"] == "http://volta"
    assert deal["estadia"] == 14 and deal["max_total"] == 3000.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_panel_roundtrip.py -v`
Expected: FAIL with `AttributeError: module 'panel' has no attribute 'build_round_trip_deals'`

- [ ] **Step 3: Write minimal implementation**

In `panel.py`, add the import at the top and the function at the end:

```python
from alerts import RoundTripAlert


def build_round_trip_deals(rt_alerts: list[RoundTripAlert], region: str) -> list[dict]:
    """One panel record per round-trip alert. `tipo:"roundtrip"` carries both legs;
    origem/destino/data/preco/url_compra mirror the ida leg (with preco = total) so the
    existing filters and sorting keep working."""
    deals: list[dict] = []
    for rt in rt_alerts:
        deals.append({
            "tipo": "roundtrip",
            "regiao": region,
            "origem": rt.ida.origin,
            "destino": rt.ida.destination,
            "data": rt.ida.departure_date.isoformat(),
            "cia": rt.ida.airline,
            "preco": rt.total,
            "paradas": rt.ida.stops,
            "direto": rt.ida.is_direct,
            "url_compra": rt.ida.booking_url,
            "azul_cheapest": False,
            "price_watch": None,
            "ida_origem": rt.ida.origin,
            "ida_destino": rt.ida.destination,
            "data_ida": rt.ida.departure_date.isoformat(),
            "cia_ida": rt.ida.airline,
            "preco_ida": rt.ida.price,
            "url_ida": rt.ida.booking_url,
            "volta_origem": rt.volta.origin,
            "volta_destino": rt.volta.destination,
            "data_volta": rt.volta.departure_date.isoformat(),
            "cia_volta": rt.volta.airline,
            "preco_volta": rt.volta.price,
            "url_volta": rt.volta.booking_url,
            "estadia": rt.stay_days,
            "max_total": rt.max_total,
        })
    return deals
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_panel_roundtrip.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add panel.py tests/test_panel_roundtrip.py
git commit -m "feat(panel): build_round_trip_deals snapshot rows"
```

---

### Task 6: Telegram round-trip message + sender

**Files:**
- Modify: `telegram_bot.py` (add `format_round_trip_alert`, `send_round_trip_alert`; extend the `from alerts import ...` line to include `RoundTripAlert`)
- Test: `tests/test_telegram_roundtrip.py` (new — format only; the sender is I/O and covered by Task 7's integration test)

**Interfaces:**
- Consumes: `alerts.RoundTripAlert`, existing `_format_brl`.
- Produces: `telegram_bot.format_round_trip_alert(rt:RoundTripAlert) -> str`; `telegram_bot.send_round_trip_alert(rt:RoundTripAlert, topic_id:int|None=None) -> bool`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_telegram_roundtrip.py
from datetime import date
import telegram_bot
from airlines.base import Flight
from alerts import RoundTripAlert


def _leg(o, d, dt, price, airline, url):
    return Flight(origin=o, destination=d, airline=airline, departure_date=dt,
                  departure_time="10h00", arrival_time="20h00", price=price,
                  is_direct=False, stops=1, booking_url=url)


def test_format_round_trip_alert_contains_both_legs():
    rt = RoundTripAlert(
        watch_name="Europa",
        ida=_leg("CNF", "CDG", date(2027, 3, 1), 1450.0, "AZUL", "http://ida"),
        volta=_leg("MXP", "CNF", date(2027, 3, 15), 1440.0, "LATAM", "http://volta"),
        stay_days=14, total=2890.0, max_total=3000.0,
    )
    msg = telegram_bot.format_round_trip_alert(rt)
    assert "IDA+VOLTA EUROPA" in msg
    assert "CNF → CDG" in msg and "MXP → CNF" in msg
    assert "01/03/2027" in msg and "15/03/2027" in msg
    assert "14 dias" in msg
    assert "R$ 2.890" in msg and "R$ 3.000" in msg
    assert "(http://ida)" in msg and "(http://volta)" in msg
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_telegram_roundtrip.py -v`
Expected: FAIL with `AttributeError: module 'telegram_bot' has no attribute 'format_round_trip_alert'`

- [ ] **Step 3: Write minimal implementation**

In `telegram_bot.py`, change the alerts import line (currently `from alerts import AzulComparison`) to:

```python
from alerts import AzulComparison, RoundTripAlert
```

Append:

```python
def format_round_trip_alert(rt: RoundTripAlert) -> str:
    ida_d = rt.ida.departure_date.strftime("%d/%m/%Y")
    volta_d = rt.volta.departure_date.strftime("%d/%m/%Y")
    now_str = datetime.now().strftime("%H:%M")
    return (
        f"🌍 *IDA+VOLTA {rt.watch_name.upper()} < {_format_brl(rt.max_total)}*\n\n"
        f"🛫 Ida:   {rt.ida.origin} → {rt.ida.destination} · {ida_d} · "
        f"{rt.ida.airline} · {_format_brl(rt.ida.price)}\n"
        f"🛬 Volta: {rt.volta.origin} → {rt.volta.destination} · {volta_d} · "
        f"{rt.volta.airline} · {_format_brl(rt.volta.price)}\n"
        f"🧳 Estadia: {rt.stay_days} dias\n"
        f"💰 Total: {_format_brl(rt.total)}  (teto {_format_brl(rt.max_total)})\n"
        f"🔗 [Reservar ida]({rt.ida.booking_url}) · [Reservar volta]({rt.volta.booking_url})\n\n"
        f"⏰ Detectado às {now_str}"
    )


async def send_round_trip_alert(rt: RoundTripAlert, topic_id: int | None = None) -> bool:
    """Returns True only on a successful send. Posts to `topic_id`; on failure retries
    once on the General thread."""
    message = format_round_trip_alert(rt)
    try:
        bot = get_bot()
    except Exception as e:
        logger.error(f"Falha ao criar bot Telegram: {e}")
        return False

    async def _send(thread_id: int | None) -> None:
        await bot.send_message(
            chat_id=TELEGRAM_CHANNEL_ID,
            text=message,
            parse_mode=ParseMode.MARKDOWN,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
            message_thread_id=thread_id,
        )

    try:
        await _send(topic_id)
    except Exception as e:
        if topic_id is None:
            logger.error(f"Falha ao enviar alerta ida+volta: {e}")
            return False
        logger.warning(f"Tópico {topic_id} falhou, tentando Geral: {e}")
        try:
            await _send(None)
        except Exception as e2:
            logger.error(f"Falha ao enviar alerta ida+volta (Geral): {e2}")
            return False

    logger.info(
        f"Alerta ida+volta enviado: {rt.ida.origin}→{rt.ida.destination} + "
        f"{rt.volta.origin}→{rt.volta.destination} R${rt.total:.2f} "
        f"({rt.stay_days}d) {rt.ida.departure_date}"
    )
    return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_telegram_roundtrip.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add telegram_bot.py tests/test_telegram_roundtrip.py
git commit -m "feat(telegram): round-trip alert message + sender"
```

---

### Task 7: wire round-trips into the cycle

**Files:**
- Modify: `cycle.py` (imports; pass `ROUND_TRIP_WATCHES` to `target_dates`; accumulate European legs; add `process_round_trips`; call it before `write_deals`)
- Test: `tests/test_cycle_roundtrip.py` (new)

**Interfaces:**
- Consumes: `config.ROUND_TRIP_WATCHES`, `alerts.evaluate_round_trip`, `alerts.round_trip_cache_key`, `panel.build_round_trip_deals`, `telegram_bot.send_round_trip_alert`, `cache.is_key_cached`, `cache.save_key`.
- Produces: `cycle.process_round_trips(rt_ida:dict[str,list[Flight]], rt_volta:dict[str,list[Flight]], watches:list[RoundTripWatch], all_deals:list[dict], ttl_hours:int) -> int` — sends de-duped alerts, appends panel deals, returns count sent.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cycle_roundtrip.py
import asyncio
from datetime import date
import cycle, config
from airlines.base import Flight


def _leg(o, d, dt, price, airline="AZUL"):
    return Flight(origin=o, destination=d, airline=airline, departure_date=dt,
                  departure_time="10h00", arrival_time="20h00", price=price,
                  is_direct=False, stops=1, booking_url=f"http://{o}{d}{dt}")


WATCH = config.RoundTripWatch(
    name="Europa", airports=("CDG",),
    depart_window=config.SearchWindow(date(2027, 3, 1), date(2027, 3, 31)),
    stay_min=13, stay_max=15, max_total=3000.0, topic_id=None,
)


def test_process_round_trips_sends_and_fills_panel(monkeypatch):
    sent_msgs = []
    saved_keys = []

    async def fake_send(rt, topic_id=None):
        sent_msgs.append(rt); return True

    async def fake_is_cached(key):
        return key in saved_keys

    async def fake_save(key, ttl_hours=24):
        saved_keys.append(key)

    monkeypatch.setattr(cycle.telegram_bot, "send_round_trip_alert", fake_send)
    monkeypatch.setattr(cycle.cache, "is_key_cached", fake_is_cached)
    monkeypatch.setattr(cycle.cache, "save_key", fake_save)

    rt_ida = {"Europa": [_leg("CNF", "CDG", date(2027, 3, 1), 1500.0)]}
    rt_volta = {"Europa": [_leg("CDG", "CNF", date(2027, 3, 15), 1400.0)]}
    all_deals = []

    async def run():
        return await cycle.process_round_trips(rt_ida, rt_volta, [WATCH], all_deals, 24)

    count = asyncio.run(run())
    assert count == 1
    assert len(sent_msgs) == 1 and sent_msgs[0].total == 2900.0
    assert len(all_deals) == 1 and all_deals[0]["tipo"] == "roundtrip"

    # second run: same combo already cached -> no new send, panel still filled
    all_deals.clear()
    count2 = asyncio.run(run())
    assert count2 == 0
    assert len(all_deals) == 1  # panel always reflects current qualifying combos
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cycle_roundtrip.py -v`
Expected: FAIL with `AttributeError: module 'cycle' has no attribute 'process_round_trips'`

- [ ] **Step 3: Write minimal implementation**

In `cycle.py`, update imports:

```python
from alerts import evaluate, evaluate_threshold, evaluate_round_trip, round_trip_cache_key
from config import (
    AZUL_HUB, GROUPS, PRICE_WATCHES, ROUND_TRIP_WATCHES,
    WINDOW_MIN_DAYS, WINDOW_MAX_DAYS, BATCH_SIZE, CACHE_TTL_HOURS,
)
```

Add the helper (module level):

```python
async def process_round_trips(rt_ida, rt_volta, watches, all_deals, ttl_hours) -> int:
    """Evaluate each round-trip watch, send de-duped Telegram alerts, and append the
    qualifying combos to the panel snapshot. Returns the number of alerts sent."""
    sent = 0
    for w in watches:
        rt_alerts = evaluate_round_trip(rt_ida.get(w.name, []), rt_volta.get(w.name, []), w)
        for rt in rt_alerts:
            key = round_trip_cache_key(rt)
            if await cache.is_key_cached(key):
                continue
            if await telegram_bot.send_round_trip_alert(rt, w.topic_id):
                await cache.save_key(key, ttl_hours)
                sent += 1
        all_deals.extend(panel.build_round_trip_deals(rt_alerts, f"{w.name} (ida+volta)"))
    return sent
```

In `run_azul_cycle`, before the route loop add the accumulators:

```python
    rt_ida: dict[str, list] = {w.name: [] for w in ROUND_TRIP_WATCHES}
    rt_volta: dict[str, list] = {w.name: [] for w in ROUND_TRIP_WATCHES}
```

Change the `target_dates` call to pass round-trip watches:

```python
        dates = routing.target_dates(
            route.non_hub, today, GROUPS, WINDOW_MIN_DAYS, WINDOW_MAX_DAYS,
            PRICE_WATCHES, ROUND_TRIP_WATCHES,
        )
```

After the `all_deals.extend(panel.build_deals(...))` line (inside the loop), accumulate European legs:

```python
        for w in ROUND_TRIP_WATCHES:
            if route.non_hub in w.airports:
                if route.origin == AZUL_HUB:
                    rt_ida[w.name].extend(flights)
                else:
                    rt_volta[w.name].extend(flights)
```

After the loop, before `panel.write_deals(all_deals, DEALS_PATH)`:

```python
    total_rt_alerts = await process_round_trips(
        rt_ida, rt_volta, ROUND_TRIP_WATCHES, all_deals, CACHE_TTL_HOURS
    )
```

Extend the final log line to include `total_rt_alerts` (add ` | ida+volta: {total_rt_alerts}` to the `CICLO AZUL CONCLUÍDO` message).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cycle_roundtrip.py -v`
Expected: PASS (both runs)

- [ ] **Step 5: Full suite regression**

Run: `python -m pytest -q`
Expected: all pass (no regressions in existing tests).

- [ ] **Step 6: Commit**

```bash
git add cycle.py tests/test_cycle_roundtrip.py
git commit -m "feat(cycle): evaluate + dispatch Europe round-trip watch"
```

---

### Task 8: panel UI renders round-trip rows

**Files:**
- Modify: `web/index.html:36-40` (add option to `#f-tipo`)
- Modify: `web/app.js` (filter predicate for `roundtrip`; sentido guard; two-leg row render)
- Verify: browser check against a locally-built encrypted snapshot

**Interfaces:**
- Consumes: panel deal dicts with `tipo:"roundtrip"` (Task 5 shape).

- [ ] **Step 1: Add the type option**

In `web/index.html`, inside `<select id="f-tipo">`, add after the `watch` option:

```html
          <option value="roundtrip">Ida+volta Europa</option>
```

- [ ] **Step 2: Update the filter predicate in `app.js`**

In `render()`, replace the `tipo` line of the filter with a version that handles round-trips and excludes them from the leg-only signal filters, and guard the sentido filter:

```javascript
    (!sentido || (d.tipo !== "roundtrip" && sentidoOf(d) === sentido)) &&
```

and replace the tipo predicate:

```javascript
    (!tipo || (
      tipo === "roundtrip" ? d.tipo === "roundtrip" :
      tipo === "azul"      ? (d.tipo !== "roundtrip" && d.azul_cheapest) :
                             (d.tipo !== "roundtrip" && d.price_watch != null)
    )) &&
```

- [ ] **Step 3: Render two-leg rows**

In `render()`, at the start of the `rows.map((d) => {…})` callback, branch for round-trips:

```javascript
  document.getElementById("rows").innerHTML = rows.map((d) => {
    if (d.tipo === "roundtrip") {
      const rota = `${esc(d.ida_origem)}→${esc(d.ida_destino)} + ${esc(d.volta_origem)}→${esc(d.volta_destino)}`;
      const datas = `${fmtDate(d.data_ida)} → ${fmtDate(d.data_volta)} <span class="muted">(${d.estadia}d)</span>`;
      return `<tr class="alert">
        <td>${rota} <span class="muted">· ${esc(d.regiao)}</span></td>
        <td>${datas}</td>
        <td>${esc(d.cia_ida)} + ${esc(d.cia_volta)}</td>
        <td>${fmtBRL(d.preco)}</td>
        <td><span class="badge watch">ida+volta</span></td>
        <td><a class="buy" href="${esc(d.url_ida)}" target="_blank" rel="noopener">ida</a> ·
            <a class="buy" href="${esc(d.url_volta)}" target="_blank" rel="noopener">volta</a></td>
      </tr>`;
    }
    const badges =
```

(the existing single-leg row code continues unchanged after this block)

- [ ] **Step 4: Update the "Alertas" summary count**

The summary line `const alertas = rows.filter((d) => d.azul_cheapest || d.price_watch != null).length;` — extend to count round-trips:

```javascript
  const alertas = rows.filter((d) => d.tipo === "roundtrip" || d.azul_cheapest || d.price_watch != null).length;
```

- [ ] **Step 5: Build a test snapshot and verify in the browser**

Create a throwaway fixture and encrypt it with the panel encryptor, then serve `web/` + the encrypted file and check rendering.

```bash
python - <<'PY'
import json, os
from datetime import date
os.environ["PANEL_PASSWORD"] = "testpass"
# a couple of normal legs + one round-trip row
deals = [
  {"tipo":"leg","regiao":"Sul","origem":"CNF","destino":"POA","data":"2026-09-10",
   "hora":"08h00","cia":"AZUL","preco":380.0,"paradas":0,"direto":True,
   "url_compra":"http://x","azul_cheapest":True,"price_watch":400.0},
  {"tipo":"roundtrip","regiao":"Europa (ida+volta)","origem":"CNF","destino":"CDG",
   "data":"2027-03-01","cia":"AZUL","preco":2890.0,"paradas":1,"direto":False,
   "url_compra":"http://ida","azul_cheapest":False,"price_watch":None,
   "ida_origem":"CNF","ida_destino":"CDG","data_ida":"2027-03-01","cia_ida":"AZUL",
   "preco_ida":1450.0,"url_ida":"http://ida","volta_origem":"MXP","volta_destino":"CNF",
   "data_volta":"2027-03-15","cia_volta":"LATAM","preco_volta":1440.0,
   "url_volta":"http://volta","estadia":14,"max_total":3000.0},
]
import panel
panel.write_deals(deals, "deals.json")
import subprocess, sys
subprocess.run([sys.executable, "scripts/encrypt_deals.py"], check=True)
os.replace("deals.enc.json", "web/deals.enc.json")
print("wrote web/deals.enc.json (password: testpass)")
PY
```

Then serve and open:

```bash
python -m http.server 8765 --directory web
```

Open `http://localhost:8765/`, unlock with `testpass`, and confirm:
- A row shows `CNF→CDG + MXP→CNF`, dates `01/03/2027 → 15/03/2027 (14d)`, `AZUL + LATAM`, `R$ 2.890`, an `ida+volta` badge, and two links (`ida`, `volta`).
- The type filter **Ida+volta Europa** shows only that row; **Azul** and **≤ limite** hide it.
- No console errors.

Clean up the throwaway file afterward:

```bash
rm -f web/deals.enc.json deals.json
```

- [ ] **Step 6: Commit**

```bash
git add web/index.html web/app.js
git commit -m "feat(panel-ui): render Europe round-trip rows + filter"
```

---

### Task 9: final verification & branch wrap-up

- [ ] **Step 1: Run the whole suite**

Run: `python -m pytest -q`
Expected: all green.

- [ ] **Step 2: Confirm the config reaches the search**

Sanity-check that European airports now request the 2027 span (no network):

```bash
python - <<'PY'
from datetime import date
import routing, config
d = routing.target_dates("CDG", date(2026,8,19), config.GROUPS,
                         config.WINDOW_MIN_DAYS, config.WINDOW_MAX_DAYS,
                         config.PRICE_WATCHES, config.ROUND_TRIP_WATCHES)
assert date(2027,2,1) in d and date(2027,6,15) in d
print("OK: CDG target_dates spans Feb 1 – Jun 15 2027 (", len(d), "dates )")
PY
```

- [ ] **Step 3: Update project memory**

Add a line to `C:\Users\vdto8\.claude\projects\C--FlightAlert\memory\MEMORY.md` and (if warranted) the flight-scraper-direction memory noting the Europe round-trip watch (< R$3.000, 13–15d stay, depart Feb–May 2027, open-jaw across the 4 countries, General topic + panel).

- [ ] **Step 4: Finish the branch**

Use `superpowers:finishing-a-development-branch` to decide merge/PR. The scheduled workflow runs on `master`, so this must land on `master` to take effect.

---

## Self-Review

**Spec coverage:**
- Pool of 8 airports, open-jaw, 13–15 stay, depart Feb–May 2027, ≤3000 → Tasks 1, 3.
- Search dates extended to Feb 1–Jun 15 2027 → Task 2 (+ Task 9 sanity check).
- One alert per departure date, "all that qualify", 24h dedup → Tasks 3, 4, 7.
- Telegram General topic, two legs, two links → Task 6.
- Panel rows + "Ida+volta Europa" filter, same encrypted snapshot → Tasks 5, 8.
- Composite dedup key → Tasks 3 (`round_trip_cache_key`), 4 (`is_key_cached`/`save_key`).

**Placeholder scan:** none — every code/test step carries full content.

**Type consistency:** `RoundTripWatch` fields (name/airports/depart_window/stay_min/stay_max/max_total/topic_id), `RoundTripAlert` fields (watch_name/ida/volta/stay_days/total/max_total), and `evaluate_round_trip`/`round_trip_cache_key`/`build_round_trip_deals`/`send_round_trip_alert`/`process_round_trips` signatures are used identically across Tasks 1, 3, 5, 6, 7, 8.
