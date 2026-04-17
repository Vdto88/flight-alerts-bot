# Google Flights Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `GoogleFlightsSearcher` (via `fast-flights`) as a fallback in the scheduler when native airline scrapers return no results.

**Architecture:** A new `airlines/google_flights.py` wraps the synchronous `fast-flights` library in an async executor. The scheduler calls it transparently when any scraper returns `[]` (or raises), filtering results by airline name before the normal threshold/cache/alert pipeline.

**Tech Stack:** Python 3.11+, `fast-flights`, `asyncio.run_in_executor`, `unittest.mock`, `pytest-asyncio`

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `airlines/google_flights.py` | `GoogleFlightsSearcher` — wraps `fast-flights`, returns `List[Flight]` |
| Create | `tests/test_google_flights.py` | Unit tests for parser, time/price helpers, and search() |
| Modify | `scheduler.py` | Add `_matches_airline`, `google_searcher`, fallback block |
| Modify | `tests/test_scheduler.py` | Update exception test + add fallback tests |
| Modify | `requirements.txt` | Add `fast-flights` |

---

## Task 1: Add fast-flights dependency

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add to requirements.txt**

Open `requirements.txt` and add after `lxml==5.4.0`:

```
fast-flights==0.2.2
```

- [ ] **Step 2: Install**

```bash
pip install fast-flights==0.2.2
```

Expected: installs without errors. Verify with:
```bash
python -c "from fast_flights import FlightData, Passengers, get_flights; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "chore: add fast-flights dependency"
```

---

## Task 2: Create GoogleFlightsSearcher — parser and helpers

**Files:**
- Create: `airlines/google_flights.py`
- Create: `tests/test_google_flights.py`

- [ ] **Step 1: Write failing tests for `_parse_time` and `_parse_price`**

Create `tests/test_google_flights.py`:

```python
import pytest
from datetime import date
from unittest.mock import MagicMock, patch
from airlines.google_flights import GoogleFlightsSearcher, _parse_time, _parse_price


def test_parse_time_am():
    assert _parse_time("7:40 AM") == "07h40"


def test_parse_time_pm():
    assert _parse_time("3:05 PM") == "15h05"


def test_parse_time_noon():
    assert _parse_time("12:00 PM") == "12h00"


def test_parse_time_midnight():
    assert _parse_time("12:00 AM") == "00h00"


def test_parse_time_empty():
    assert _parse_time("") == ""


def test_parse_price_brl_symbol():
    assert _parse_price("R$289") == 289.0


def test_parse_price_with_space():
    assert _parse_price("R$ 1.290,50") == 1290.50


def test_parse_price_plain():
    assert _parse_price("450") == 450.0


def test_parse_price_invalid():
    assert _parse_price("grátis") is None
```

- [ ] **Step 2: Run to confirm failures**

```bash
pytest tests/test_google_flights.py -v
```

Expected: `ModuleNotFoundError` or `ImportError` (file doesn't exist yet).

- [ ] **Step 3: Create `airlines/google_flights.py` with helpers**

```python
import asyncio
import logging
import re
from datetime import date
from functools import partial
from typing import List, Optional

from fast_flights import FlightData, Passengers, get_flights

from airlines.base import Flight, FlightSearcher
from config import REQUEST_TIMEOUT

logger = logging.getLogger(__name__)

_BOOKING_BASE = "https://www.google.com/travel/flights"


def _parse_time(raw: str) -> str:
    """Convert '7:40 AM' / '3:05 PM' to '07h40' / '15h05'."""
    if not raw:
        return ""
    m = re.match(r"(\d{1,2}):(\d{2})\s*(AM|PM)", raw.strip(), re.IGNORECASE)
    if not m:
        return ""
    hour, minute, period = int(m.group(1)), int(m.group(2)), m.group(3).upper()
    if period == "PM" and hour != 12:
        hour += 12
    elif period == "AM" and hour == 12:
        hour = 0
    return f"{hour:02d}h{minute:02d}"


def _parse_price(raw: str) -> Optional[float]:
    """Extract a float from strings like 'R$289', 'R$ 1.290,50', '450'."""
    cleaned = re.sub(r"[^\d,.]", "", raw)
    # Brazilian format: dots as thousands separator, comma as decimal
    if "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


class GoogleFlightsSearcher(FlightSearcher):
    AIRLINE_NAME = "GOOGLE_FALLBACK"

    async def search(self, origin: str, destination: str, departure_date: date) -> List[Flight]:
        date_str = departure_date.strftime("%Y-%m-%d")
        fn = partial(
            get_flights,
            flight_data=[FlightData(date=date_str, from_airport=origin, to_airport=destination)],
            passengers=Passengers(adults=1),
            trip="one-way",
            currency="BRL",
        )
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(None, fn)
        except Exception as e:
            logger.warning(f"Google Flights/{origin}→{destination} {departure_date}: {e}")
            return []

        return self._parse(result, origin, destination, departure_date)

    def _parse(self, result, origin: str, destination: str, departure_date: date) -> List[Flight]:
        flights: List[Flight] = []
        try:
            for ff in result.flights:
                price = _parse_price(ff.price or "")
                if price is None:
                    continue
                stops = int(ff.stops) if ff.stops is not None else 0
                if stops > 1:
                    continue
                dep_time = _parse_time(ff.departure or "")
                arr_time = _parse_time(ff.arrival or "")
                booking_url = (
                    f"{_BOOKING_BASE}?hl=pt-BR"
                    f"&origin={origin}&destination={destination}"
                    f"&outbound={departure_date.strftime('%Y-%m-%d')}"
                )
                flights.append(Flight(
                    origin=origin,
                    destination=destination,
                    airline=ff.name or "GOOGLE_FALLBACK",
                    departure_date=departure_date,
                    departure_time=dep_time,
                    arrival_time=arr_time,
                    price=price,
                    is_direct=(stops == 0),
                    stops=stops,
                    booking_url=booking_url,
                ))
        except Exception as e:
            logger.error(f"Google Flights parse error: {e}")
        return flights
```

- [ ] **Step 4: Run tests and confirm they pass**

```bash
pytest tests/test_google_flights.py::test_parse_time_am tests/test_google_flights.py::test_parse_time_pm tests/test_google_flights.py::test_parse_time_noon tests/test_google_flights.py::test_parse_time_midnight tests/test_google_flights.py::test_parse_time_empty tests/test_google_flights.py::test_parse_price_brl_symbol tests/test_google_flights.py::test_parse_price_with_space tests/test_google_flights.py::test_parse_price_plain tests/test_google_flights.py::test_parse_price_invalid -v
```

Expected: all 9 PASS.

- [ ] **Step 5: Commit**

```bash
git add airlines/google_flights.py tests/test_google_flights.py
git commit -m "feat: GoogleFlightsSearcher with time/price helpers"
```

---

## Task 3: Test and validate `_parse` and `search()`

**Files:**
- Modify: `tests/test_google_flights.py`

- [ ] **Step 1: Add tests for `_parse` and `search()`**

Append to `tests/test_google_flights.py`:

```python
def _make_ff_flight(name="GOL Linhas Aéreas", departure="7:40 AM",
                    arrival="9:10 AM", stops=0, price="R$289"):
    f = MagicMock()
    f.name = name
    f.departure = departure
    f.arrival = arrival
    f.stops = stops
    f.price = price
    return f


def _make_ff_result(flights):
    r = MagicMock()
    r.flights = flights
    return r


def test_parse_valid_flight():
    searcher = GoogleFlightsSearcher()
    result = _make_ff_result([_make_ff_flight()])
    flights = searcher._parse(result, "GRU", "CGH", date(2026, 5, 15))
    assert len(flights) == 1
    f = flights[0]
    assert f.airline == "GOL Linhas Aéreas"
    assert f.price == 289.0
    assert f.departure_time == "07h40"
    assert f.arrival_time == "09h10"
    assert f.is_direct is True
    assert f.stops == 0
    assert f.origin == "GRU"
    assert f.destination == "CGH"


def test_parse_filters_more_than_one_stop():
    searcher = GoogleFlightsSearcher()
    result = _make_ff_result([_make_ff_flight(stops=2)])
    assert searcher._parse(result, "GRU", "CGH", date(2026, 5, 15)) == []


def test_parse_skips_invalid_price():
    searcher = GoogleFlightsSearcher()
    result = _make_ff_result([_make_ff_flight(price="grátis")])
    assert searcher._parse(result, "GRU", "CGH", date(2026, 5, 15)) == []


def test_parse_empty_result():
    searcher = GoogleFlightsSearcher()
    result = _make_ff_result([])
    assert searcher._parse(result, "GRU", "CGH", date(2026, 5, 15)) == []


async def test_search_returns_flights():
    searcher = GoogleFlightsSearcher()
    ff_result = _make_ff_result([_make_ff_flight()])
    with patch("airlines.google_flights.get_flights", return_value=ff_result):
        flights = await searcher.search("GRU", "CGH", date(2026, 5, 15))
    assert len(flights) == 1
    assert flights[0].price == 289.0


async def test_search_returns_empty_on_exception():
    searcher = GoogleFlightsSearcher()
    with patch("airlines.google_flights.get_flights", side_effect=Exception("network error")):
        flights = await searcher.search("GRU", "CGH", date(2026, 5, 15))
    assert flights == []
```

- [ ] **Step 2: Run tests**

```bash
pytest tests/test_google_flights.py -v
```

Expected: all 15 PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_google_flights.py
git commit -m "test: full coverage for GoogleFlightsSearcher"
```

---

## Task 4: Add `_matches_airline` + fallback to scheduler

**Files:**
- Modify: `scheduler.py`
- Modify: `tests/test_scheduler.py`

- [ ] **Step 1: Write failing tests for `_matches_airline`**

Append to `tests/test_scheduler.py`:

```python
def test_matches_airline_gol():
    from scheduler import _matches_airline
    assert _matches_airline("GOL Linhas Aéreas", "GOL") is True
    assert _matches_airline("Gol", "GOL") is True
    assert _matches_airline("LATAM Airlines", "GOL") is False


def test_matches_airline_latam():
    from scheduler import _matches_airline
    assert _matches_airline("LATAM Airlines", "LATAM") is True
    assert _matches_airline("Latam", "LATAM") is True
    assert _matches_airline("Azul", "LATAM") is False


def test_matches_airline_azul():
    from scheduler import _matches_airline
    assert _matches_airline("Azul Linhas Aéreas", "AZUL") is True
    assert _matches_airline("AZUL", "AZUL") is True
    assert _matches_airline("GOL", "AZUL") is False


async def test_run_cycle_uses_fallback_when_scraper_returns_empty(monkeypatch):
    import scheduler
    import cache
    import telegram_bot

    cheap_flight = _flight(price=289.90, airline="GOL Linhas Aéreas")

    monkeypatch.setattr(scheduler, "SEARCHERS", {
        "GOL": MagicMock(search_range=AsyncMock(return_value=[]))
    })
    monkeypatch.setattr(scheduler, "google_searcher",
        MagicMock(search_range=AsyncMock(return_value=[cheap_flight]))
    )
    monkeypatch.setattr(cache, "purge_expired", AsyncMock())
    monkeypatch.setattr(cache, "is_cached", AsyncMock(return_value=False))
    monkeypatch.setattr(cache, "save_to_cache", AsyncMock())
    monkeypatch.setattr(telegram_bot, "send_alert", AsyncMock())
    monkeypatch.setattr(scheduler, "ROUTES", [
        {"from": "CNF", "to": "GRU", "threshold": 350, "airlines": ["GOL"]}
    ])

    await scheduler.run_cycle()

    telegram_bot.send_alert.assert_called_once_with(cheap_flight)


async def test_run_cycle_fallback_filters_wrong_airline(monkeypatch):
    import scheduler
    import cache
    import telegram_bot

    latam_flight = _flight(price=289.90, airline="LATAM Airlines")

    monkeypatch.setattr(scheduler, "SEARCHERS", {
        "GOL": MagicMock(search_range=AsyncMock(return_value=[]))
    })
    monkeypatch.setattr(scheduler, "google_searcher",
        MagicMock(search_range=AsyncMock(return_value=[latam_flight]))
    )
    monkeypatch.setattr(cache, "purge_expired", AsyncMock())
    monkeypatch.setattr(cache, "is_cached", AsyncMock(return_value=False))
    monkeypatch.setattr(cache, "save_to_cache", AsyncMock())
    monkeypatch.setattr(telegram_bot, "send_alert", AsyncMock())
    monkeypatch.setattr(scheduler, "ROUTES", [
        {"from": "CNF", "to": "GRU", "threshold": 350, "airlines": ["GOL"]}
    ])

    await scheduler.run_cycle()

    telegram_bot.send_alert.assert_not_called()


async def test_run_cycle_uses_fallback_on_exception(monkeypatch):
    import scheduler
    import cache
    import telegram_bot

    cheap_flight = _flight(price=289.90, airline="GOL Linhas Aéreas")

    monkeypatch.setattr(scheduler, "SEARCHERS", {
        "GOL": MagicMock(search_range=AsyncMock(side_effect=RuntimeError("API down")))
    })
    monkeypatch.setattr(scheduler, "google_searcher",
        MagicMock(search_range=AsyncMock(return_value=[cheap_flight]))
    )
    monkeypatch.setattr(cache, "purge_expired", AsyncMock())
    monkeypatch.setattr(cache, "is_cached", AsyncMock(return_value=False))
    monkeypatch.setattr(cache, "save_to_cache", AsyncMock())
    monkeypatch.setattr(telegram_bot, "send_alert", AsyncMock())
    monkeypatch.setattr(scheduler, "ROUTES", [
        {"from": "CNF", "to": "GRU", "threshold": 350, "airlines": ["GOL"]}
    ])

    await scheduler.run_cycle()

    telegram_bot.send_alert.assert_called_once_with(cheap_flight)
```

- [ ] **Step 2: Run to confirm failures**

```bash
pytest tests/test_scheduler.py::test_matches_airline_gol tests/test_scheduler.py::test_run_cycle_uses_fallback_when_scraper_returns_empty -v
```

Expected: `ImportError` on `_matches_airline` (not defined yet).

- [ ] **Step 3: Update `scheduler.py`**

Replace the full contents of `scheduler.py` with:

```python
import asyncio
import logging
import time
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

import cache
import telegram_bot
from airlines.base import FlightSearcher
from airlines.gol import GolSearcher
from airlines.latam import LatamSearcher
from airlines.azul import AzulSearcher
from airlines.google_flights import GoogleFlightsSearcher
from config import ROUTES, CYCLE_MINUTES, CACHE_TTL_HOURS, SEARCH_DAYS_AHEAD, BATCH_SIZE

logger = logging.getLogger(__name__)

SEARCHERS: dict[str, FlightSearcher] = {
    "GOL": GolSearcher(),
    "LATAM": LatamSearcher(),
    "AZUL": AzulSearcher(),
}

google_searcher = GoogleFlightsSearcher()

_AIRLINE_ALIASES: dict[str, list[str]] = {
    "GOL":   ["gol"],
    "LATAM": ["latam"],
    "AZUL":  ["azul"],
}


def _matches_airline(flight_airline: str, expected: str) -> bool:
    aliases = _AIRLINE_ALIASES.get(expected.upper(), [expected.lower()])
    name_lower = flight_airline.lower()
    return any(alias in name_lower for alias in aliases)


async def run_cycle() -> None:
    start = time.monotonic()
    total_candidates = 0
    total_alerts = 0
    total_errors = 0

    logger.info(f"CICLO INICIADO — {len(ROUTES)} rotas")
    await cache.purge_expired()

    for route in ROUTES:
        origin = route["from"]
        dest = route["to"]
        threshold = route["threshold"]
        airline_names = [n for n in route["airlines"] if n in SEARCHERS]

        tasks = [SEARCHERS[name].search_range(origin, dest, SEARCH_DAYS_AHEAD, BATCH_SIZE) for name in airline_names]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for name, result in zip(airline_names, results):
            if isinstance(result, Exception):
                logger.warning(f"ERRO {name}/{origin}→{dest}: {result}")
                total_errors += 1
                result = []

            if not result:
                logger.info(f"{name}/{origin}→{dest}: fallback para Google Flights")
                gf_flights = await google_searcher.search_range(origin, dest, SEARCH_DAYS_AHEAD, BATCH_SIZE)
                result = [f for f in gf_flights if _matches_airline(f.airline, name)]

            below = [f for f in result if f.price < threshold and f.stops <= 1]
            logger.info(
                f"{name}/{origin}→{dest}: {len(result)} voos encontrados, {len(below)} abaixo do threshold"
            )
            total_candidates += len(below)

            for flight in below:
                if not await cache.is_cached(flight):
                    await telegram_bot.send_alert(flight)
                    await cache.save_to_cache(flight, CACHE_TTL_HOURS)
                    total_alerts += 1

    elapsed = time.monotonic() - start
    logger.info(
        f"CICLO CONCLUÍDO — {elapsed:.0f}s | rotas: {len(ROUTES)} | "
        f"candidatos: {total_candidates} | alertas: {total_alerts} | erros: {total_errors}"
    )


def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_cycle,
        trigger="interval",
        minutes=CYCLE_MINUTES,
        next_run_time=datetime.now(),
        id="flight_cycle",
    )
    return scheduler
```

- [ ] **Step 4: Update the existing exception test** — it now needs `google_searcher` mocked

In `tests/test_scheduler.py`, find `test_run_cycle_handles_searcher_exception` and replace it:

```python
async def test_run_cycle_handles_searcher_exception(monkeypatch):
    import scheduler
    import cache
    import telegram_bot

    monkeypatch.setattr(scheduler, "SEARCHERS", {
        "GOL": MagicMock(search_range=AsyncMock(side_effect=RuntimeError("API down")))
    })
    monkeypatch.setattr(scheduler, "google_searcher",
        MagicMock(search_range=AsyncMock(return_value=[]))
    )
    monkeypatch.setattr(cache, "purge_expired", AsyncMock())
    monkeypatch.setattr(telegram_bot, "send_alert", AsyncMock())
    monkeypatch.setattr(scheduler, "ROUTES", [
        {"from": "CNF", "to": "GRU", "threshold": 350, "airlines": ["GOL"]}
    ])

    await scheduler.run_cycle()
    telegram_bot.send_alert.assert_not_called()
```

- [ ] **Step 5: Run all tests**

```bash
pytest tests/test_scheduler.py tests/test_google_flights.py -v
```

Expected: all tests PASS.

- [ ] **Step 6: Run full test suite to check for regressions**

```bash
pytest -v
```

Expected: all tests PASS.

- [ ] **Step 7: Commit**

```bash
git add scheduler.py tests/test_scheduler.py
git commit -m "feat: Google Flights fallback in scheduler with airline filtering"
```
