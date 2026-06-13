# Azul Cheaper Alert — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the flight bot around a single signal — alert on Telegram whenever Azul is the cheapest airline on a route+date — sourced from Google Flights, run as a single pass under GitHub Actions cron.

**Architecture:** Google Flights (`fast_flights`) is the only data source. A pure `evaluate()` in `alerts.py` decides, per route+date, whether Azul's cheapest fare beats the cheapest competitor. `cycle.py` orchestrates fetch → evaluate → send → dedup; `main.py` runs one pass and exits. The dead direct scrapers, the threshold/generic-alert model, and APScheduler are removed. Miles code stays dormant.

**Tech Stack:** Python 3.11, `fast_flights`, `httpx`, `python-telegram-bot`, `aiosqlite`, `pytest`/`pytest-asyncio` (`asyncio_mode = auto`), GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-06-13-azul-cheaper-alert-design.md`

---

## File Structure

**Create:** `alerts.py`, `cycle.py`, `tests/test_alerts.py`, `tests/test_cycle.py`, `.github/workflows/azul-alert.yml`
**Modify:** `config.py`, `airlines/base.py`, `telegram_bot.py`, `main.py`, `requirements.txt`, `tests/test_base.py`, `tests/test_telegram_bot.py`
**Delete:** `airlines/gol.py`, `airlines/latam.py`, `airlines/azul.py`, `scheduler.py`, `tests/test_gol.py`, `tests/test_latam.py`, `tests/test_azul.py`, `tests/test_scheduler.py`
**Untouched (dormant):** `airlines/smiles_miles.py`, `airlines/azul_miles.py`, `scripts/harvest_cookies.py`, `tests/test_smiles_miles.py`, `tests/test_azul_miles.py`, `cache.py`

> All commands run from the repo root `C:\FlightAlert`. The active branch is `feature/azul-cheaper-alert`.

---

### Task 1: Remove dead code (scrapers, scheduler, APScheduler)

These target dead endpoints (Akamai 406 / removed) and the old threshold model. Nothing surviving imports them except tests, which are deleted here too. `main.py` will temporarily fail to import `scheduler` — it is rewritten in Task 7 and is not exercised by the test suite in between.

**Files:**
- Delete: `airlines/gol.py`, `airlines/latam.py`, `airlines/azul.py`, `scheduler.py`
- Delete: `tests/test_gol.py`, `tests/test_latam.py`, `tests/test_azul.py`, `tests/test_scheduler.py`
- Modify: `requirements.txt`

- [ ] **Step 1: Delete the dead modules and their tests**

```bash
git rm airlines/gol.py airlines/latam.py airlines/azul.py scheduler.py \
       tests/test_gol.py tests/test_latam.py tests/test_azul.py tests/test_scheduler.py
```

- [ ] **Step 2: Drop APScheduler from `requirements.txt`**

Remove this line (only `scheduler.py` used it):

```
APScheduler==3.10.4
```

- [ ] **Step 3: Run the suite to confirm nothing else referenced them**

Run: `python -m pytest -q`
Expected: PASS (remaining tests: base, cache, google_flights, telegram_bot, azul_miles, smiles_miles). No import errors.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore: remove dead direct scrapers, scheduler, APScheduler"
```

---

### Task 2: Rewrite `config.py` for the Azul-cheapest model

Drop `ROUTES`, `GOL_API_KEY`, and the other now-unused constants. Keep `TELEGRAM_*`, the miles constants (`scripts/harvest_cookies.py` imports `MILES_ROUTES`/`MILES_DAYS_AHEAD`), and add the Azul config.

**Files:**
- Modify: `config.py` (full replacement below)

- [ ] **Step 1: Replace `config.py` with:**

```python
import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID: str = os.environ.get("TELEGRAM_CHANNEL_ID", "")

# --- Azul-cheapest alert ---
AZUL_HUB: str = "CNF"
AZUL_DESTINATIONS: list[str] = [
    # Domestic
    "GIG", "SDU", "CGH", "SSA", "SLZ", "IGU", "FLN", "NVT",
    # Patagonia / Chile / Argentina (rarely fire — kept on purpose)
    "FTE", "PNT", "PMC", "PUQ", "SCL", "BRC",
]

# Rolling window of departure dates to check, in days from today.
WINDOW_MIN_DAYS: int = 30
WINDOW_MAX_DAYS: int = 90

# Optional: pin explicit ISO dates for a destination instead of the rolling window.
# e.g. {"SCL": ["2026-12-15", "2026-12-16"]}
AZUL_DATE_OVERRIDES: dict[str, list[str]] = {}

BATCH_SIZE: int = 7          # concurrent Google Flights queries per batch
CACHE_TTL_HOURS: int = 24    # dedup window

# --- Miles (dormant; consumed only by scripts/harvest_cookies.py) ---
MILES_ROUTES = [
    {"from": "CNF", "to": "IGU", "miles_threshold": 15000, "program": "SMILES"},
    {"from": "IGU", "to": "CNF", "miles_threshold": 15000, "program": "SMILES"},
    {"from": "CNF", "to": "IGU", "miles_threshold": 20000, "program": "AZUL_MILES"},
    {"from": "IGU", "to": "CNF", "miles_threshold": 20000, "program": "AZUL_MILES"},
]
MILES_DAYS_AHEAD: int = 30
```

- [ ] **Step 2: Sanity-check imports**

Run: `python -c "import config; print(len(config.AZUL_DESTINATIONS)); from config import MILES_ROUTES, MILES_DAYS_AHEAD; print('miles ok')"`
Expected: `14` then `miles ok`.

- [ ] **Step 3: Run the suite**

Run: `python -m pytest -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add config.py
git commit -m "feat: replace ROUTES/threshold config with Azul-cheapest config"
```

---

### Task 3: Add `search_dates()` to `FlightSearcher`

The cycle checks an arbitrary date list (window or overrides), not a contiguous "next N days". Add a date-list-driven batch fetch to the base class.

**Files:**
- Modify: `airlines/base.py`
- Test: `tests/test_base.py`

- [ ] **Step 1: Write the failing tests** — append to `tests/test_base.py`:

```python
from airlines.base import FlightSearcher


class _FakeSearcher(FlightSearcher):
    AIRLINE_NAME = "FAKE"

    def __init__(self, fail_on=None):
        self.fail_on = fail_on
        self.seen = []

    async def search(self, origin, destination, departure_date):
        self.seen.append(departure_date)
        if self.fail_on is not None and departure_date == self.fail_on:
            raise RuntimeError("boom")
        return [Flight(origin, destination, "FAKE", departure_date,
                       "10h00", "11h00", 100.0, True, 0, "url")]


async def test_search_dates_returns_one_flight_per_date():
    s = _FakeSearcher()
    dates = [date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 3)]
    flights = await s.search_dates("CNF", "SSA", dates, batch_size=2)
    assert len(flights) == 3
    assert {f.departure_date for f in flights} == set(dates)


async def test_search_dates_skips_failed_date():
    s = _FakeSearcher(fail_on=date(2026, 7, 2))
    dates = [date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 3)]
    flights = await s.search_dates("CNF", "SSA", dates, batch_size=3)
    assert len(flights) == 2
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_base.py -q`
Expected: FAIL — `AttributeError: 'FlightSearcher' object has no attribute 'search_dates'` (or `_FakeSearcher`).

- [ ] **Step 3: Implement `search_dates`** — add this method to `FlightSearcher` in `airlines/base.py` (right after `search_range`):

```python
    async def search_dates(
        self, origin: str, destination: str, dates: List[date], batch_size: int = 7
    ) -> List[Flight]:
        """Search an explicit list of departure dates in concurrent batches."""
        all_flights: List[Flight] = []
        for start in range(0, len(dates), batch_size):
            batch = dates[start:start + batch_size]
            tasks = [self.search(origin, destination, d) for d in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, list):
                    all_flights.extend(result)
                else:
                    logger.warning(f"{self.AIRLINE_NAME} search_dates error: {result}")
        return all_flights
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_base.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add airlines/base.py tests/test_base.py
git commit -m "feat: add search_dates() for explicit date lists"
```

---

### Task 4: Create `alerts.py` with `evaluate()`

The pure core. Given all flights for one route across dates, return Azul-cheapest alerts.

**Files:**
- Create: `alerts.py`
- Test: `tests/test_alerts.py`

- [ ] **Step 1: Write the failing tests** — create `tests/test_alerts.py`:

```python
from datetime import date

from airlines.base import Flight
from alerts import evaluate, AzulAlert, AzulComparison


def _f(airline, price, dep=date(2026, 7, 15), stops=0):
    return Flight("CNF", "SSA", airline, dep, "12h00", "13h15",
                  price, stops == 0, stops, "https://book")


def test_azul_cheapest_fires_with_comparison():
    flights = [_f("Azul", 300.0), _f("LATAM", 396.0), _f("Gol", 410.0)]
    alerts = evaluate(flights)
    assert len(alerts) == 1
    a = alerts[0]
    assert isinstance(a, AzulAlert)
    assert a.flight.airline == "Azul"
    assert a.comparison == AzulComparison(competitor="LATAM",
                                          competitor_price=396.0, savings=96.0)


def test_no_alert_when_competitor_cheaper():
    flights = [_f("Azul", 400.0), _f("LATAM", 396.0)]
    assert evaluate(flights) == []


def test_no_alert_on_tie():
    flights = [_f("Azul", 396.0), _f("LATAM", 396.0)]
    assert evaluate(flights) == []


def test_no_alert_when_azul_is_only_airline():
    flights = [_f("Azul", 300.0), _f("Azul", 320.0)]
    assert evaluate(flights) == []


def test_no_alert_when_no_azul():
    flights = [_f("LATAM", 300.0), _f("Gol", 320.0)]
    assert evaluate(flights) == []


def test_picks_cheapest_azul_and_cheapest_competitor():
    flights = [_f("Azul", 350.0), _f("Azul", 300.0),
               _f("LATAM", 500.0), _f("Gol", 396.0)]
    alerts = evaluate(flights)
    assert len(alerts) == 1
    assert alerts[0].flight.price == 300.0
    assert alerts[0].comparison.competitor == "Gol"
    assert alerts[0].comparison.savings == 96.0


def test_each_date_evaluated_independently():
    d1, d2 = date(2026, 7, 15), date(2026, 7, 16)
    flights = [
        _f("Azul", 300.0, dep=d1), _f("LATAM", 396.0, dep=d1),   # fires
        _f("Azul", 500.0, dep=d2), _f("LATAM", 396.0, dep=d2),   # no
    ]
    alerts = evaluate(flights)
    assert {a.flight.departure_date for a in alerts} == {d1}


def test_ignores_zero_or_missing_price():
    flights = [_f("Azul", 0.0), _f("Azul", 300.0), _f("LATAM", 396.0)]
    alerts = evaluate(flights)
    assert len(alerts) == 1
    assert alerts[0].flight.price == 300.0


def test_stops_not_filtered():
    # A 2-stop Azul still wins if it is cheaper.
    flights = [_f("Azul", 300.0, stops=2), _f("LATAM", 396.0, stops=0)]
    alerts = evaluate(flights)
    assert len(alerts) == 1
    assert alerts[0].flight.stops == 2
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_alerts.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'alerts'`.

- [ ] **Step 3: Implement `alerts.py`:**

```python
import logging
from dataclasses import dataclass

from airlines.base import Flight

logger = logging.getLogger(__name__)


@dataclass
class AzulComparison:
    competitor: str          # cheapest non-Azul airline name, e.g. "LATAM"
    competitor_price: float  # BRL
    savings: float           # competitor_price - azul_price


@dataclass
class AzulAlert:
    flight: Flight           # the cheapest Azul flight on that date
    comparison: AzulComparison


def _is_azul(airline: str) -> bool:
    return "azul" in airline.lower()


def evaluate(flights: list[Flight]) -> list[AzulAlert]:
    """For one route's flights across dates, return Azul-cheapest alerts.

    Fires when, on a given departure date, the cheapest Azul fare is strictly
    lower than the cheapest competitor fare. Stops are not filtered. Requires
    at least one non-Azul competitor on the date.
    """
    by_date: dict = {}
    for f in flights:
        if f.price is None or f.price <= 0:
            continue
        by_date.setdefault(f.departure_date, []).append(f)

    alerts: list[AzulAlert] = []
    for _, day_flights in by_date.items():
        azul = [f for f in day_flights if _is_azul(f.airline)]
        others = [f for f in day_flights if not _is_azul(f.airline)]
        if not azul or not others:
            continue
        azul_best = min(azul, key=lambda f: f.price)
        other_best = min(others, key=lambda f: f.price)
        if azul_best.price < other_best.price:
            alerts.append(AzulAlert(
                flight=azul_best,
                comparison=AzulComparison(
                    competitor=other_best.airline,
                    competitor_price=other_best.price,
                    savings=round(other_best.price - azul_best.price, 2),
                ),
            ))
    return alerts
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_alerts.py -q`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add alerts.py tests/test_alerts.py
git commit -m "feat: add Azul-cheapest alert evaluation (pure)"
```

---

### Task 5: Add the Azul alert format + sender to `telegram_bot.py`

**Files:**
- Modify: `telegram_bot.py`
- Test: `tests/test_telegram_bot.py`

- [ ] **Step 1: Write the failing test** — append to `tests/test_telegram_bot.py`:

```python
from datetime import date as _date
from airlines.base import Flight as _Flight
from alerts import AzulComparison as _AzulComparison
import telegram_bot as _tb


def test_format_azul_alert_contains_comparison():
    f = _Flight("CNF", "SSA", "Azul", _date(2026, 7, 15), "12h00", "13h15",
                300.0, True, 0, "https://book")
    comp = _AzulComparison(competitor="LATAM", competitor_price=396.0, savings=96.0)
    msg = _tb.format_azul_alert(f, comp)
    assert "AZUL É A MAIS BARATA" in msg
    assert "CNF → SSA" in msg
    assert "R$ 300,00" in msg
    assert "LATAM" in msg
    assert "R$ 396,00" in msg
    assert "economia de R$ 96,00" in msg
    assert "Direto" in msg
    assert "https://book" in msg


def test_format_azul_alert_shows_stops_plural():
    f = _Flight("CNF", "PUQ", "Azul", _date(2026, 7, 15), "06h00", "20h00",
                900.0, False, 2, "https://book")
    comp = _AzulComparison(competitor="LATAM", competitor_price=1200.0, savings=300.0)
    msg = _tb.format_azul_alert(f, comp)
    assert "2 paradas" in msg
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_telegram_bot.py -q`
Expected: FAIL — `AttributeError: module 'telegram_bot' has no attribute 'format_azul_alert'`.

- [ ] **Step 3: Implement** — add to `telegram_bot.py`. First add the import at the top (after the existing `from airlines.base import Flight`):

```python
from alerts import AzulComparison
```

Then add a BRL helper and the two functions:

```python
def _format_brl(value: float) -> str:
    return f"R$ {value:_.2f}".replace("_", "X").replace(".", ",").replace("X", ".")


def _stops_label(flight: Flight) -> str:
    if flight.is_direct or flight.stops == 0:
        return "Direto"
    return f"{flight.stops} parada" + ("s" if flight.stops > 1 else "")


def format_azul_alert(flight: Flight, comparison: AzulComparison) -> str:
    dep_date = flight.departure_date.strftime("%d/%m/%Y")
    now_str = datetime.now().strftime("%H:%M")
    return (
        f"🔵 *AZUL É A MAIS BARATA*\n\n"
        f"🛫 {flight.origin} → {flight.destination}\n"
        f"💰 {_format_brl(flight.price)}  (Azul)\n"
        f"📊 vs {_format_brl(comparison.competitor_price)} ({comparison.competitor}) "
        f"— economia de {_format_brl(comparison.savings)}\n"
        f"📅 {dep_date} • {flight.departure_time} → {flight.arrival_time}\n"
        f"🏢 Azul • {_stops_label(flight)}\n"
        f"🔗 [Reservar agora]({flight.booking_url})\n\n"
        f"⏰ Detectado às {now_str}"
    )


async def send_azul_alert(flight: Flight, comparison: AzulComparison) -> None:
    bot = get_bot()
    message = format_azul_alert(flight, comparison)
    try:
        await bot.send_message(
            chat_id=TELEGRAM_CHANNEL_ID,
            text=message,
            parse_mode=ParseMode.MARKDOWN,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
        logger.info(
            f"Alerta Azul enviado: {flight.origin}→{flight.destination} "
            f"R${flight.price:.2f} (vs {comparison.competitor} R${comparison.competitor_price:.2f}) "
            f"{flight.departure_date}"
        )
    except Exception as e:
        logger.error(f"Falha ao enviar alerta Azul: {e}")
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_telegram_bot.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add telegram_bot.py tests/test_telegram_bot.py
git commit -m "feat: add Azul-cheapest Telegram alert format and sender"
```

---

### Task 6: Create `cycle.py` (orchestration)

Builds routes + target dates, fetches Google Flights, evaluates, sends + dedups.

**Files:**
- Create: `cycle.py`
- Test: `tests/test_cycle.py`

- [ ] **Step 1: Write the failing tests** — create `tests/test_cycle.py`:

```python
from datetime import date, timedelta

import cache
import telegram_bot
import cycle
from airlines.base import Flight
from airlines.google_flights import GoogleFlightsSearcher


def test_build_routes_has_both_directions_and_count():
    routes = cycle.build_routes()
    assert ("CNF", "SSA") in routes
    assert ("SSA", "CNF") in routes
    assert len(routes) == 28               # 14 destinations x 2 directions
    assert all("CNF" in (o, d) for o, d in routes)


def test_target_dates_uses_window():
    today = date(2026, 1, 1)
    dates = cycle.target_dates("SSA", today)
    assert dates[0] == today + timedelta(days=30)
    assert dates[-1] == today + timedelta(days=90)
    assert len(dates) == 61


def test_target_dates_uses_override(monkeypatch):
    monkeypatch.setattr(cycle, "AZUL_DATE_OVERRIDES", {"SCL": ["2026-12-15", "2026-12-16"]})
    dates = cycle.target_dates("SCL", date(2026, 1, 1))
    assert dates == [date(2026, 12, 15), date(2026, 12, 16)]


async def test_run_cycle_sends_alert_when_azul_cheapest(monkeypatch):
    await cache.init_db()
    d = date(2026, 7, 15)
    canned = [
        Flight("CNF", "SSA", "Azul", d, "12h00", "13h15", 300.0, True, 0, "u"),
        Flight("CNF", "SSA", "LATAM", d, "07h00", "08h15", 396.0, True, 0, "u"),
    ]

    async def fake_search_dates(self, origin, destination, dates, batch_size=7):
        return canned if (origin, destination) == ("CNF", "SSA") else []

    monkeypatch.setattr(GoogleFlightsSearcher, "search_dates", fake_search_dates)

    sent = []

    async def fake_send(flight, comparison):
        sent.append((flight, comparison))

    monkeypatch.setattr(telegram_bot, "send_azul_alert", fake_send)

    await cycle.run_azul_cycle()

    assert len(sent) == 1
    flight, comp = sent[0]
    assert "azul" in flight.airline.lower()
    assert comp.competitor == "LATAM"


async def test_run_cycle_dedups_within_ttl(monkeypatch):
    await cache.init_db()
    d = date(2026, 7, 15)
    canned = [
        Flight("CNF", "SSA", "Azul", d, "12h00", "13h15", 300.0, True, 0, "u"),
        Flight("CNF", "SSA", "LATAM", d, "07h00", "08h15", 396.0, True, 0, "u"),
    ]

    async def fake_search_dates(self, origin, destination, dates, batch_size=7):
        return canned if (origin, destination) == ("CNF", "SSA") else []

    monkeypatch.setattr(GoogleFlightsSearcher, "search_dates", fake_search_dates)
    sent = []

    async def fake_send(flight, comparison):
        sent.append(flight)

    monkeypatch.setattr(telegram_bot, "send_azul_alert", fake_send)

    await cycle.run_azul_cycle()
    await cycle.run_azul_cycle()   # second pass: same flight, must be deduped

    assert len(sent) == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_cycle.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'cycle'`.

- [ ] **Step 3: Implement `cycle.py`:**

```python
import logging
from datetime import date, timedelta

import cache
import telegram_bot
from airlines.google_flights import GoogleFlightsSearcher
from alerts import evaluate
from config import (
    AZUL_HUB, AZUL_DESTINATIONS, WINDOW_MIN_DAYS, WINDOW_MAX_DAYS,
    AZUL_DATE_OVERRIDES, BATCH_SIZE, CACHE_TTL_HOURS,
)

logger = logging.getLogger(__name__)

_searcher = GoogleFlightsSearcher()


def build_routes() -> list[tuple[str, str]]:
    """CNF ↔ each destination, both directions."""
    routes: list[tuple[str, str]] = []
    for dest in AZUL_DESTINATIONS:
        routes.append((AZUL_HUB, dest))
        routes.append((dest, AZUL_HUB))
    return routes


def target_dates(non_hub: str, today: date) -> list[date]:
    """Explicit override dates for the non-hub endpoint, else the rolling window."""
    override = AZUL_DATE_OVERRIDES.get(non_hub)
    if override:
        return [date.fromisoformat(s) for s in override]
    return [today + timedelta(days=n) for n in range(WINDOW_MIN_DAYS, WINDOW_MAX_DAYS + 1)]


async def run_azul_cycle() -> None:
    today = date.today()
    await cache.purge_expired()
    total_alerts = 0
    total_errors = 0

    for origin, dest in build_routes():
        non_hub = dest if origin == AZUL_HUB else origin
        dates = target_dates(non_hub, today)
        try:
            flights = await _searcher.search_dates(origin, dest, dates, BATCH_SIZE)
        except Exception as e:
            logger.warning(f"AZUL {origin}→{dest}: erro na busca: {e}")
            total_errors += 1
            continue

        alerts = evaluate(flights)
        for alert in alerts:
            if not await cache.is_cached(alert.flight):
                await telegram_bot.send_azul_alert(alert.flight, alert.comparison)
                await cache.save_to_cache(alert.flight, CACHE_TTL_HOURS)
                total_alerts += 1

        logger.info(
            f"AZUL {origin}→{dest}: {len(flights)} voos, {len(alerts)} datas com Azul mais barata"
        )

    logger.info(f"CICLO AZUL CONCLUÍDO — alertas: {total_alerts} | erros: {total_errors}")
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_cycle.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add cycle.py tests/test_cycle.py
git commit -m "feat: add Azul-cheapest cycle orchestration"
```

---

### Task 7: Rewrite `main.py` as a single pass

**Files:**
- Modify: `main.py` (full replacement below)

- [ ] **Step 1: Replace `main.py` with:**

```python
import asyncio
import logging
import logging.handlers
from pathlib import Path

import cache
from cycle import run_azul_cycle


def setup_logging() -> None:
    Path("logs").mkdir(exist_ok=True)
    fmt = logging.Formatter("[%(asctime)s] %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    console = logging.StreamHandler()
    console.setFormatter(fmt)

    file_handler = logging.handlers.TimedRotatingFileHandler(
        "logs/bot.log", when="midnight", backupCount=7, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(console)
    root.addHandler(file_handler)


async def main() -> None:
    setup_logging()
    log = logging.getLogger(__name__)
    await cache.init_db()
    await run_azul_cycle()
    log.info("Passe concluído.")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Verify it imports cleanly (no more `scheduler` import)**

Run: `python -c "import main; print('import ok')"`
Expected: `import ok`.

- [ ] **Step 3: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS (all remaining tests).

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "feat: single-pass main.py (cron-driven, no APScheduler)"
```

- [ ] **Step 5 (OPTIONAL local smoke — manual):** With a real `.env` (Telegram tokens), temporarily narrow the scan to one nearby date to confirm end-to-end without a huge run:

```bash
# PowerShell, temporary env overrides are not supported in config; instead edit config.py
# briefly: AZUL_DESTINATIONS=["SSA"], WINDOW_MIN_DAYS=1, WINDOW_MAX_DAYS=2 — run — then revert.
python main.py
```
Expected: log lines `AZUL CNF→SSA: N voos ...` and `CICLO AZUL CONCLUÍDO`. A Telegram message only if Azul actually undercuts on those dates. **Revert the config edit and do not commit it.**

---

### Task 8: GitHub Actions workflow

**Files:**
- Create: `.github/workflows/azul-alert.yml`

- [ ] **Step 1: Create `.github/workflows/azul-alert.yml`:**

```yaml
name: Azul cheaper alert

on:
  schedule:
    - cron: "0 11,17,23 * * *"   # ~08:00 / 14:00 / 20:00 BRT (UTC-3)
  workflow_dispatch: {}

concurrency:
  group: azul-alert
  cancel-in-progress: false

jobs:
  run:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install deps
        run: pip install -r requirements.txt

      - name: Restore dedup cache
        uses: actions/cache@v4
        with:
          path: data
          key: azul-dedup-${{ github.run_id }}
          restore-keys: |
            azul-dedup-

      - name: Run one pass
        env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHANNEL_ID: ${{ secrets.TELEGRAM_CHANNEL_ID }}
        run: python main.py
```

> The `key` is unique per run and `restore-keys` matches the latest prior cache — the standard "always save, restore most recent" pattern so `data/cache.db` (dedup state) survives across ephemeral runs.

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/azul-alert.yml
git commit -m "ci: schedule Azul alert 3x/day via GitHub Actions"
```

---

### Task 9: Deploy & validate (operational — needs the user's Telegram tokens)

This validates the one empirical unknown: does Google Flights answer from the GitHub runner IP?

- [ ] **Step 1: Set repo secrets** (requires `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHANNEL_ID` values):

```bash
gh secret set TELEGRAM_BOT_TOKEN  --repo Vdto88/flight-alerts-bot
gh secret set TELEGRAM_CHANNEL_ID --repo Vdto88/flight-alerts-bot
```

- [ ] **Step 2: Get the branch onto the repo and merge** (open a PR or push to master):

```bash
git push -u origin feature/azul-cheaper-alert
# review, then merge into master (the workflow's schedule runs on the default branch)
```

- [ ] **Step 3: Trigger a manual run and watch it**

```bash
gh workflow run "Azul cheaper alert" --repo Vdto88/flight-alerts-bot
gh run watch --repo Vdto88/flight-alerts-bot
```
Expected: job succeeds; logs show `N voos` (non-zero) per route and `CICLO AZUL CONCLUÍDO`.

- [ ] **Step 4: Interpret**
  - Non-zero `voos` → Google Flights works from GitHub IPs. Done.
  - Zero `voos` everywhere / errors → likely IP-blocked. **Fallback:** disable the schedule and run the same `python main.py` locally via Windows Task Scheduler 3×/day (residential IP, verified working). No code change.

---

## Self-Review

**Spec coverage:**
- Single source = Google Flights → Task 1 (delete others), Task 6 (cycle uses only `GoogleFlightsSearcher`). ✓
- `evaluate()` pure, Azul-cheapest, ≥1 competitor, stops ignored, ignore zero price → Task 4 + tests. ✓
- Rolling 30–90 window + per-destination overrides → Task 2 (config), Task 6 (`target_dates`) + tests. ✓
- 28 routes (CNF ↔ 14, both ways) → Task 2 + Task 6 (`build_routes`) + test. ✓
- Dedup 24h via existing `cache.cache_key()` → Task 6 + `test_run_cycle_dedups_within_ttl`. ✓ (cache.py unchanged, as specified.)
- Telegram Azul format with comparison + stops → Task 5 + tests. ✓
- Single-pass `main.py`, no APScheduler → Task 7, Task 1. ✓
- GitHub Actions 3×/day + `actions/cache` + secrets; local fallback → Task 8, Task 9. ✓
- Miles dormant/untouched → no task touches `smiles_miles.py`/`azul_miles.py`/`harvest_cookies.py`; config keeps `MILES_*`. ✓
- First-run IP validation → Task 9. ✓

**Placeholder scan:** No TBD/TODO; every code step has complete code. The only "edit then revert" is the clearly-marked optional manual smoke in Task 7 Step 5. ✓

**Type consistency:** `evaluate() -> list[AzulAlert]`; `AzulAlert.flight`/`.comparison`; `AzulComparison(competitor, competitor_price, savings)` — used identically in `alerts.py`, `telegram_bot.format_azul_alert`/`send_azul_alert`, and `cycle.run_azul_cycle`. `search_dates(origin, destination, dates, batch_size)` defined in Task 3, called identically in Task 6 and its test. ✓
