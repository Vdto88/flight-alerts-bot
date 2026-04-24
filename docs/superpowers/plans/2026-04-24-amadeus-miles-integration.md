# Amadeus + Miles Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace broken airline HTTP scrapers with Amadeus API for cash prices and add miles monitoring (Smiles, LATAM Pass, TudoAzul) with Telegram alerts.

**Architecture:** `AmadeusSearcher` uses a two-phase approach — `scan_dates()` finds cheap dates in one API call, `search()` fetches details only for those dates. Three independent miles searchers run in parallel in a new `miles_cycle`. `Flight` gains `currency` + `miles_program` fields so cash and miles share the same alert/cache pipeline.

**Tech Stack:** Python 3.11+, amadeus-python SDK, httpx, aiosqlite, APScheduler, python-telegram-bot, pytest + pytest-asyncio

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `airlines/base.py` | Add `currency`, `miles_program` to `Flight`; update `cache_key` |
| Modify | `config.py` | Update `ROUTES`, add `MILES_ROUTES`, add Amadeus env vars |
| Modify | `requirements.txt` | Add `amadeus` SDK |
| Modify | `.env.example` | Add `AMADEUS_API_KEY`, `AMADEUS_API_SECRET` |
| New | `airlines/amadeus.py` | Cash searcher via Amadeus API (replaces gol/latam/azul) |
| New | `airlines/smiles.py` | Smiles miles searcher |
| New | `airlines/latam_miles.py` | LATAM Pass miles searcher |
| New | `airlines/azul_miles.py` | TudoAzul miles searcher |
| Modify | `telegram_bot.py` | Branch `format_alert` on `currency` |
| Modify | `scheduler.py` | `cash_cycle` + `miles_cycle` in parallel |
| Modify | `tests/test_base.py` | Tests for new Flight fields + cache_key |
| New | `tests/test_amadeus.py` | Tests for AmadeusSearcher |
| New | `tests/test_smiles.py` | Tests for SmilesSearcher |
| New | `tests/test_latam_miles.py` | Tests for LatamMilesSearcher |
| New | `tests/test_azul_miles.py` | Tests for AzulMilesSearcher |
| Modify | `tests/test_telegram_bot.py` | Tests for miles alert format |
| Modify | `tests/test_scheduler.py` | Tests for cash_cycle + miles_cycle |
| Delete | `airlines/gol.py` | Replaced by Amadeus |
| Delete | `airlines/latam.py` | Replaced by Amadeus |
| Delete | `airlines/azul.py` | Replaced by Amadeus |
| Delete | `tests/test_gol.py` | |
| Delete | `tests/test_latam.py` | |
| Delete | `tests/test_azul.py` | |

---

## Task 1: Extend Flight dataclass

**Files:**
- Modify: `airlines/base.py`
- Modify: `tests/test_base.py`

- [ ] **Step 1: Write failing tests for new fields**

Add to `tests/test_base.py`:

```python
from datetime import date
from airlines.base import Flight


def _base_flight(**kwargs) -> Flight:
    defaults = dict(
        origin="CNF", destination="GRU", airline="GOL",
        departure_date=date(2026, 5, 15), departure_time="07h40",
        arrival_time="09h10", price=289.90, is_direct=True, stops=0,
        booking_url="https://example.com",
    )
    defaults.update(kwargs)
    return Flight(**defaults)


def test_flight_defaults_to_brl_currency():
    f = _base_flight()
    assert f.currency == "BRL"
    assert f.miles_program == ""


def test_flight_accepts_milhas_currency():
    f = _base_flight(price=8500.0, currency="MILHAS", miles_program="SMILES")
    assert f.currency == "MILHAS"
    assert f.miles_program == "SMILES"


def test_cache_key_brl_excludes_empty_program():
    f = _base_flight(price=289.90)
    key = f.cache_key()
    assert "BRL" in key
    assert key.endswith("|BRL|")


def test_cache_key_miles_includes_program():
    f = _base_flight(price=8500.0, currency="MILHAS", miles_program="SMILES")
    key = f.cache_key()
    assert "MILHAS" in key
    assert "SMILES" in key


def test_cash_and_miles_cache_keys_differ():
    cash = _base_flight(price=289.90)
    miles = _base_flight(price=289.90, currency="MILHAS", miles_program="SMILES")
    assert cash.cache_key() != miles.cache_key()
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_base.py -v
```
Expected: FAIL with `TypeError: Flight.__init__() got unexpected keyword argument 'currency'`

- [ ] **Step 3: Update `airlines/base.py`**

Replace the `Flight` dataclass and `cache_key` method:

```python
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import List
import asyncio
import logging

logger = logging.getLogger(__name__)


@dataclass
class Flight:
    origin: str
    destination: str
    airline: str
    departure_date: date
    departure_time: str
    arrival_time: str
    price: float
    is_direct: bool
    stops: int
    booking_url: str
    currency: str = "BRL"
    miles_program: str = ""

    def cache_key(self) -> str:
        price_floor = math.floor(self.price / 10) * 10
        return f"{self.airline}|{self.origin}|{self.destination}|{self.departure_date}|{price_floor}|{self.currency}|{self.miles_program}"


class FlightSearcher(ABC):
    AIRLINE_NAME: str = ""

    @abstractmethod
    async def search(self, origin: str, destination: str, departure_date: date) -> List[Flight]:
        """Search flights for a single departure date. Returns [] on any error."""

    async def search_range(self, origin: str, destination: str, days_ahead: int = 60, batch_size: int = 7) -> List[Flight]:
        """Search the next `days_ahead` days in batches of `batch_size` dates."""
        today = date.today()
        dates = [today + timedelta(days=i) for i in range(1, days_ahead + 1)]
        all_flights: List[Flight] = []

        for batch_start in range(0, len(dates), batch_size):
            batch = dates[batch_start:batch_start + batch_size]
            tasks = [self.search(origin, destination, d) for d in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, list):
                    all_flights.extend(result)
                else:
                    logger.warning(f"{self.AIRLINE_NAME} batch error: {result}")

        return all_flights
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_base.py -v
```
Expected: all 5 new tests PASS

- [ ] **Step 5: Commit**

```bash
git add airlines/base.py tests/test_base.py
git commit -m "feat: extend Flight with currency + miles_program fields"
```

---

## Task 2: Update config

**Files:**
- Modify: `config.py`
- Modify: `.env.example`

- [ ] **Step 1: Update `config.py`**

Replace the entire file:

```python
import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID: str = os.environ.get("TELEGRAM_CHANNEL_ID", "")
GOL_API_KEY: str = os.getenv("GOL_API_KEY", "aaa-bbb")
AMADEUS_API_KEY: str = os.getenv("AMADEUS_API_KEY", "")
AMADEUS_API_SECRET: str = os.getenv("AMADEUS_API_SECRET", "")

ROUTES = [
    {"from": "CNF", "to": "GRU", "threshold": 350,  "airlines": ["GOL", "LATAM", "AZUL"]},
    {"from": "CNF", "to": "CGH", "threshold": 350,  "airlines": ["GOL", "LATAM", "AZUL"]},
    {"from": "CNF", "to": "GIG", "threshold": 400,  "airlines": ["GOL", "LATAM", "AZUL"]},
    {"from": "CNF", "to": "SDU", "threshold": 400,  "airlines": ["GOL", "LATAM", "AZUL"]},
    {"from": "CNF", "to": "POA", "threshold": 500,  "airlines": ["GOL", "LATAM", "AZUL"]},
    {"from": "CNF", "to": "IGU", "threshold": 500,  "airlines": ["GOL", "LATAM", "AZUL"]},
    {"from": "CNF", "to": "SLZ", "threshold": 600,  "airlines": ["GOL", "LATAM", "AZUL"]},
    {"from": "GRU", "to": "LIS", "threshold": 2000, "airlines": ["LATAM", "GOL"]},
    {"from": "GRU", "to": "MIA", "threshold": 1500, "airlines": ["LATAM", "GOL"]},
]

MILES_ROUTES = [
    {"from": "CNF", "to": "GRU", "thresholds": {"SMILES": 10000, "LATAM_PASS": 10000, "TUDOAZUL": 14000}},
    {"from": "CNF", "to": "CGH", "thresholds": {"SMILES": 10000, "LATAM_PASS": 10000, "TUDOAZUL": 14000}},
    {"from": "CNF", "to": "GIG", "thresholds": {"SMILES": 10000, "LATAM_PASS": 10000, "TUDOAZUL": 14000}},
    {"from": "CNF", "to": "SDU", "thresholds": {"SMILES": 10000, "LATAM_PASS": 10000, "TUDOAZUL": 14000}},
    {"from": "CNF", "to": "POA", "thresholds": {"SMILES": 10000, "LATAM_PASS": 10000, "TUDOAZUL": 14000}},
    {"from": "CNF", "to": "IGU", "thresholds": {"SMILES": 10000, "LATAM_PASS": 10000, "TUDOAZUL": 14000}},
    {"from": "CNF", "to": "SLZ", "thresholds": {"SMILES": 10000, "LATAM_PASS": 10000, "TUDOAZUL": 14000}},
]

SEARCH_DAYS_AHEAD: int = 60
BATCH_SIZE: int = 7
CYCLE_MINUTES: int = 45
CACHE_TTL_HOURS: int = 24
REQUEST_TIMEOUT: float = 15.0
REQUEST_RETRIES: int = 2
REQUEST_RETRY_BACKOFF: float = 2.0
```

- [ ] **Step 2: Update `.env.example`**

Replace the file contents:

```
TELEGRAM_BOT_TOKEN=your_token_here
TELEGRAM_CHANNEL_ID=@your_channel
GOL_API_KEY=aaa-bbb
AMADEUS_API_KEY=your_amadeus_key
AMADEUS_API_SECRET=your_amadeus_secret
```

- [ ] **Step 3: Update `requirements.txt`**

Add the amadeus SDK line:

```
httpx==0.27.0
python-telegram-bot==21.3.0
APScheduler==3.10.4
aiosqlite==0.20.0
beautifulsoup4==4.12.3
lxml==5.4.0
fast-flights==2.2
python-dotenv==1.0.1
amadeus==9.0.0

# dev / test
pytest==8.1.1
pytest-asyncio==0.23.6
pytest-mock==3.14.0
```

- [ ] **Step 4: Install the new dependency**

```
pip install amadeus==9.0.0
```

Expected: `Successfully installed amadeus-9.0.0`

- [ ] **Step 5: Register Amadeus credentials**

Go to https://developers.amadeus.com → sign up → create a new app → copy API Key and API Secret to your `.env` file:

```
AMADEUS_API_KEY=<your key>
AMADEUS_API_SECRET=<your secret>
```

The free Self-Service tier covers both test and production environments. Start with the test environment (`hostname='test.api.amadeus.com'`).

- [ ] **Step 6: Commit**

```bash
git add config.py .env.example requirements.txt
git commit -m "feat: add Amadeus config, MILES_ROUTES, and new CNF routes"
```

---

## Task 3: Amadeus cash searcher

**Files:**
- Create: `airlines/amadeus.py`
- Create: `tests/test_amadeus.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_amadeus.py`:

```python
import pytest
from datetime import date
from unittest.mock import MagicMock, patch, AsyncMock

from airlines.amadeus import AmadeusSearcher


SAMPLE_FLIGHT_DATES_RESPONSE = [
    {"departureDate": "2026-05-15", "price": {"total": "289.50"}},
    {"departureDate": "2026-05-16", "price": {"total": "450.00"}},
    {"departureDate": "2026-05-17", "price": {"total": "310.00"}},
]

SAMPLE_FLIGHT_OFFERS_RESPONSE = [
    {
        "price": {"grandTotal": "289.50", "currency": "BRL"},
        "validatingAirlineCodes": ["G3"],
        "itineraries": [
            {
                "segments": [
                    {
                        "departure": {"iataCode": "CNF", "at": "2026-05-15T07:40:00"},
                        "arrival": {"iataCode": "GRU", "at": "2026-05-15T09:10:00"},
                        "carrierCode": "G3",
                        "numberOfStops": 0,
                    }
                ]
            }
        ],
    }
]


def _make_amadeus_response(data):
    r = MagicMock()
    r.data = data
    return r


def test_parse_returns_flights():
    searcher = AmadeusSearcher("GOL")
    flights = searcher._parse(SAMPLE_FLIGHT_OFFERS_RESPONSE, "CNF", "GRU", date(2026, 5, 15))
    assert len(flights) == 1
    f = flights[0]
    assert f.airline == "GOL"
    assert f.origin == "CNF"
    assert f.destination == "GRU"
    assert f.price == 289.50
    assert f.departure_time == "07h40"
    assert f.arrival_time == "09h10"
    assert f.is_direct is True
    assert f.stops == 0
    assert f.currency == "BRL"
    assert f.miles_program == ""


def test_parse_filters_two_stops():
    data = [
        {
            "price": {"grandTotal": "200.00", "currency": "BRL"},
            "validatingAirlineCodes": ["G3"],
            "itineraries": [
                {
                    "segments": [
                        {"departure": {"iataCode": "CNF", "at": "2026-05-15T07:00:00"},
                         "arrival": {"iataCode": "GRU", "at": "2026-05-15T14:00:00"},
                         "carrierCode": "G3", "numberOfStops": 0},
                        {"departure": {"iataCode": "GRU", "at": "2026-05-15T15:00:00"},
                         "arrival": {"iataCode": "SDU", "at": "2026-05-15T16:00:00"},
                         "carrierCode": "G3", "numberOfStops": 0},
                        {"departure": {"iataCode": "SDU", "at": "2026-05-15T17:00:00"},
                         "arrival": {"iataCode": "GIG", "at": "2026-05-15T18:00:00"},
                         "carrierCode": "G3", "numberOfStops": 0},
                    ]
                }
            ],
        }
    ]
    searcher = AmadeusSearcher("GOL")
    # 3 segments = 2 connections = stops > 1, should be filtered
    assert searcher._parse(data, "CNF", "GIG", date(2026, 5, 15)) == []


def test_parse_empty_data():
    searcher = AmadeusSearcher("LATAM")
    assert searcher._parse([], "CNF", "GRU", date(2026, 5, 15)) == []


async def test_scan_dates_returns_date_price_tuples():
    searcher = AmadeusSearcher("GOL")
    mock_response = _make_amadeus_response(SAMPLE_FLIGHT_DATES_RESPONSE)

    with patch.object(searcher, "_get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.shopping.flight_dates.get.return_value = mock_response
        mock_get_client.return_value = mock_client

        results = await searcher.scan_dates("CNF", "GRU", days_ahead=60)

    assert len(results) == 3
    assert results[0] == (date(2026, 5, 15), 289.50)
    assert results[1] == (date(2026, 5, 16), 450.00)


async def test_scan_dates_returns_empty_on_error():
    from amadeus import ResponseError
    searcher = AmadeusSearcher("GOL")

    with patch.object(searcher, "_get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.shopping.flight_dates.get.side_effect = ResponseError(MagicMock())
        mock_get_client.return_value = mock_client

        results = await searcher.scan_dates("CNF", "GRU")

    assert results == []


async def test_search_returns_flights():
    searcher = AmadeusSearcher("GOL")
    mock_response = _make_amadeus_response(SAMPLE_FLIGHT_OFFERS_RESPONSE)

    with patch.object(searcher, "_get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.shopping.flight_offers_search.get.return_value = mock_response
        mock_get_client.return_value = mock_client

        flights = await searcher.search("CNF", "GRU", date(2026, 5, 15))

    assert len(flights) == 1
    assert flights[0].price == 289.50


async def test_search_returns_empty_on_error():
    from amadeus import ResponseError
    searcher = AmadeusSearcher("GOL")

    with patch.object(searcher, "_get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.shopping.flight_offers_search.get.side_effect = ResponseError(MagicMock())
        mock_get_client.return_value = mock_client

        flights = await searcher.search("CNF", "GRU", date(2026, 5, 15))

    assert flights == []
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_amadeus.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'airlines.amadeus'`

- [ ] **Step 3: Create `airlines/amadeus.py`**

```python
import asyncio
import logging
from datetime import date, timedelta
from functools import partial
from typing import List, Tuple

from amadeus import Client, ResponseError

from config import AMADEUS_API_KEY, AMADEUS_API_SECRET
from airlines.base import Flight, FlightSearcher

logger = logging.getLogger(__name__)

_IATA_CODES = {
    "GOL": "G3",
    "LATAM": "JJ",
    "AZUL": "AD",
}

_BOOKING_URLS = {
    "GOL": "https://www.smiles.com.br/passagem-de-aviao/compre-com-dinheiro",
    "LATAM": "https://www.latamairlines.com/br/pt/oferta-voos",
    "AZUL": "https://viagem.voeazul.com.br/travelShopping",
}


class AmadeusSearcher(FlightSearcher):
    def __init__(self, airline_name: str):
        self.airline_name = airline_name
        self.iata_code = _IATA_CODES[airline_name]
        self.AIRLINE_NAME = airline_name
        self._client: Client | None = None

    def _get_client(self) -> Client:
        if self._client is None:
            self._client = Client(
                client_id=AMADEUS_API_KEY,
                client_secret=AMADEUS_API_SECRET,
            )
        return self._client

    async def scan_dates(self, origin: str, destination: str, days_ahead: int = 60) -> List[Tuple[date, float]]:
        """Phase 1: one API call returns cheapest price per date across the range."""
        client = self._get_client()
        loop = asyncio.get_running_loop()
        fn = partial(
            client.shopping.flight_dates.get,
            origin=origin,
            destination=destination,
            oneWay=True,
        )
        try:
            response = await loop.run_in_executor(None, fn)
        except ResponseError as e:
            logger.warning(f"Amadeus flight-dates {origin}→{destination}: {e}")
            return []

        cutoff = date.today() + timedelta(days=days_ahead)
        results = []
        for item in response.data:
            dep_date_str = item.get("departureDate", "")
            price_str = item.get("price", {}).get("total", "")
            try:
                dep_date = date.fromisoformat(dep_date_str)
                price = float(price_str)
            except (ValueError, TypeError):
                continue
            if dep_date <= cutoff:
                results.append((dep_date, price))
        return results

    async def search(self, origin: str, destination: str, departure_date: date) -> List[Flight]:
        """Phase 2: detailed offers for a specific date."""
        client = self._get_client()
        loop = asyncio.get_running_loop()
        fn = partial(
            client.shopping.flight_offers_search.get,
            originLocationCode=origin,
            destinationLocationCode=destination,
            departureDate=departure_date.strftime("%Y-%m-%d"),
            adults=1,
            currencyCode="BRL",
            includedAirlineCodes=self.iata_code,
            max=10,
        )
        try:
            response = await loop.run_in_executor(None, fn)
        except ResponseError as e:
            logger.warning(f"Amadeus flight-offers {origin}→{destination} {departure_date}: {e}")
            return []

        return self._parse(response.data, origin, destination, departure_date)

    def _parse(self, data: list, origin: str, destination: str, departure_date: date) -> List[Flight]:
        flights = []
        for offer in data:
            try:
                price = float(offer["price"]["grandTotal"])
                itinerary = offer["itineraries"][0]
                segments = itinerary["segments"]
                stops = sum(s.get("numberOfStops", 0) for s in segments) + max(0, len(segments) - 1)
                if stops > 1:
                    continue
                dep_at = segments[0]["departure"]["at"]
                arr_at = segments[-1]["arrival"]["at"]
                dep_time = dep_at[11:16].replace(":", "h") if len(dep_at) >= 16 else ""
                arr_time = arr_at[11:16].replace(":", "h") if len(arr_at) >= 16 else ""
                date_str = departure_date.strftime("%Y-%m-%d")
                booking_url = (
                    f"{_BOOKING_URLS[self.airline_name]}"
                    f"?originAirportCode={origin}&destinationAirportCode={destination}"
                    f"&departureDate={date_str}&adults=1"
                )
                flights.append(Flight(
                    origin=origin,
                    destination=destination,
                    airline=self.airline_name,
                    departure_date=departure_date,
                    departure_time=dep_time,
                    arrival_time=arr_time,
                    price=price,
                    is_direct=(stops == 0),
                    stops=stops,
                    booking_url=booking_url,
                ))
            except (KeyError, IndexError, ValueError, TypeError) as e:
                logger.debug(f"Amadeus parse skip: {e}")
        return flights
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_amadeus.py -v
```
Expected: all 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add airlines/amadeus.py tests/test_amadeus.py
git commit -m "feat: add AmadeusSearcher with two-phase date scan + offer fetch"
```

---

## Task 4: Smiles miles searcher

**Files:**
- Create: `airlines/smiles.py`
- Create: `tests/test_smiles.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_smiles.py`:

```python
import pytest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from airlines.smiles import SmilesSearcher


SAMPLE_SMILES_RESPONSE = {
    "requestedFlightSegmentList": [
        {
            "flightList": [
                {
                    "departure": {"date": "2026-05-15", "hour": "07:40", "airport": {"code": "CNF"}},
                    "arrival": {"hour": "09:10", "airport": {"code": "GRU"}},
                    "stops": 0,
                    "available": True,
                    "fareList": [
                        {
                            "type": "SMILES_CLUB",
                            "miles": {"quantity": 8500, "originalQuantity": 10000},
                        }
                    ],
                }
            ]
        }
    ]
}


def test_parse_returns_miles_flight():
    searcher = SmilesSearcher()
    flights = searcher._parse(SAMPLE_SMILES_RESPONSE, "CNF", "GRU", date(2026, 5, 15))
    assert len(flights) == 1
    f = flights[0]
    assert f.airline == "GOL"
    assert f.price == 8500.0
    assert f.currency == "MILHAS"
    assert f.miles_program == "SMILES"
    assert f.departure_time == "07h40"
    assert f.is_direct is True


def test_parse_picks_lowest_miles():
    data = {
        "requestedFlightSegmentList": [{
            "flightList": [{
                "departure": {"date": "2026-05-15", "hour": "07:40", "airport": {"code": "CNF"}},
                "arrival": {"hour": "09:10", "airport": {"code": "GRU"}},
                "stops": 0,
                "available": True,
                "fareList": [
                    {"type": "SMILES_CLUB", "miles": {"quantity": 8500, "originalQuantity": 10000}},
                    {"type": "SMILES",      "miles": {"quantity": 7200, "originalQuantity": 9000}},
                ],
            }]
        }]
    }
    searcher = SmilesSearcher()
    flights = searcher._parse(data, "CNF", "GRU", date(2026, 5, 15))
    assert flights[0].price == 7200.0


def test_parse_skips_unavailable():
    data = {
        "requestedFlightSegmentList": [{
            "flightList": [{
                "departure": {"date": "2026-05-15", "hour": "07:40", "airport": {"code": "CNF"}},
                "arrival": {"hour": "09:10", "airport": {"code": "GRU"}},
                "stops": 0,
                "available": False,
                "fareList": [{"type": "SMILES_CLUB", "miles": {"quantity": 8500}}],
            }]
        }]
    }
    searcher = SmilesSearcher()
    assert searcher._parse(data, "CNF", "GRU", date(2026, 5, 15)) == []


def test_parse_filters_two_stops():
    data = {
        "requestedFlightSegmentList": [{
            "flightList": [{
                "departure": {"date": "2026-05-15", "hour": "07:40", "airport": {"code": "CNF"}},
                "arrival": {"hour": "15:00", "airport": {"code": "GRU"}},
                "stops": 2,
                "available": True,
                "fareList": [{"type": "SMILES_CLUB", "miles": {"quantity": 8500}}],
            }]
        }]
    }
    searcher = SmilesSearcher()
    assert searcher._parse(data, "CNF", "GRU", date(2026, 5, 15)) == []


def test_parse_empty_response():
    searcher = SmilesSearcher()
    assert searcher._parse({}, "CNF", "GRU", date(2026, 5, 15)) == []


async def test_search_returns_miles_flights():
    searcher = SmilesSearcher()
    mock_response = MagicMock()
    mock_response.json.return_value = SAMPLE_SMILES_RESPONSE
    mock_response.raise_for_status = MagicMock()

    with patch("airlines.smiles.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        flights = await searcher.search("CNF", "GRU", date(2026, 5, 15))

    assert len(flights) == 1
    assert flights[0].currency == "MILHAS"
    assert flights[0].miles_program == "SMILES"


async def test_search_returns_empty_on_403():
    searcher = SmilesSearcher()
    mock_resp = MagicMock()
    mock_resp.status_code = 403
    err = httpx.HTTPStatusError("403", request=MagicMock(), response=mock_resp)

    with patch("airlines.smiles.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=err)
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        flights = await searcher.search("CNF", "GRU", date(2026, 5, 15))

    assert flights == []
```

- [ ] **Step 2: Run to verify failure**

```
pytest tests/test_smiles.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'airlines.smiles'`

- [ ] **Step 3: Create `airlines/smiles.py`**

```python
import asyncio
import logging
from datetime import date
from typing import List

import httpx

from config import GOL_API_KEY, REQUEST_TIMEOUT, REQUEST_RETRIES, REQUEST_RETRY_BACKOFF
from airlines.base import Flight, FlightSearcher

logger = logging.getLogger(__name__)

_BASE_URL = "https://api-air-flightsearch-prd.smiles.com.br/v1/airlines/search"
_BOOKING_BASE = "https://www.smiles.com.br/emissao-com-milhas"


class SmilesSearcher(FlightSearcher):
    AIRLINE_NAME = "SMILES"

    async def search(self, origin: str, destination: str, departure_date: date) -> List[Flight]:
        params = {
            "departureDate": departure_date.strftime("%Y-%m-%d"),
            "originAirportCode": origin,
            "destinationAirportCode": destination,
            "adults": 1,
            "cabinType": "economic",
            "currencyCode": "SMILES",
        }
        headers = {
            "api-key": GOL_API_KEY,
            "x-api-key": GOL_API_KEY,
            "region": "BRAZIL",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Origin": "https://www.smiles.com.br",
            "Referer": "https://www.smiles.com.br/",
        }

        for attempt in range(REQUEST_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                    response = await client.get(_BASE_URL, params=params, headers=headers)
                    response.raise_for_status()
                    return self._parse(response.json(), origin, destination, departure_date)
            except httpx.HTTPStatusError as e:
                logger.warning(f"Smiles/{origin}→{destination} {departure_date}: HTTP {e.response.status_code}")
                return []
            except Exception as e:
                logger.warning(f"Smiles/{origin}→{destination} tentativa {attempt + 1}: {e}")
                if attempt < REQUEST_RETRIES - 1:
                    await asyncio.sleep(REQUEST_RETRY_BACKOFF)

        return []

    def _parse(self, data: dict, origin: str, destination: str, departure_date: date) -> List[Flight]:
        flights: List[Flight] = []
        try:
            for segment in data.get("requestedFlightSegmentList", []):
                for f in segment.get("flightList", []):
                    if not f.get("available", True):
                        continue
                    stops = f.get("stops", 0)
                    if stops > 1:
                        continue

                    fare_list = f.get("fareList", [])
                    if not fare_list:
                        continue

                    miles = None
                    for fare in fare_list:
                        miles_block = fare.get("miles", {})
                        qty = miles_block.get("quantity") or miles_block.get("originalQuantity")
                        if qty is not None:
                            val = int(qty)
                            if miles is None or val < miles:
                                miles = val
                    if miles is None:
                        continue

                    dep = f.get("departure", {})
                    arr = f.get("arrival", {})
                    dep_date_str = dep.get("date", "")
                    try:
                        dep_date = date.fromisoformat(dep_date_str)
                    except (ValueError, TypeError):
                        continue

                    dep_time = dep.get("hour", "").replace(":", "h")
                    arr_time = arr.get("hour", "").replace(":", "h")
                    date_str = departure_date.strftime("%Y-%m-%d")
                    booking_url = (
                        f"{_BOOKING_BASE}?originAirportCode={origin}"
                        f"&destinationAirportCode={destination}"
                        f"&departureDate={date_str}&adults=1&cabinType=economic"
                    )

                    flights.append(Flight(
                        origin=origin,
                        destination=destination,
                        airline="GOL",
                        departure_date=dep_date,
                        departure_time=dep_time,
                        arrival_time=arr_time,
                        price=float(miles),
                        is_direct=(stops == 0),
                        stops=stops,
                        booking_url=booking_url,
                        currency="MILHAS",
                        miles_program="SMILES",
                    ))
        except Exception as e:
            logger.error(f"Smiles parse error: {e}")
        return flights
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_smiles.py -v
```
Expected: all 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add airlines/smiles.py tests/test_smiles.py
git commit -m "feat: add SmilesSearcher for miles monitoring"
```

---

## Task 5: LATAM Pass miles searcher

**Files:**
- Create: `airlines/latam_miles.py`
- Create: `tests/test_latam_miles.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_latam_miles.py`:

```python
import pytest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from airlines.latam_miles import LatamMilesSearcher


SAMPLE_LATAM_MILES_RESPONSE = {
    "itineraries": [
        {
            "price": {"grandTotal": 8000.0},
            "segments": [
                {
                    "departure": {"at": "2026-05-15T07:40:00"},
                    "arrival":   {"at": "2026-05-15T09:10:00"},
                    "numberOfStops": 0,
                }
            ],
        }
    ]
}


def test_parse_returns_miles_flight():
    searcher = LatamMilesSearcher()
    flights = searcher._parse(SAMPLE_LATAM_MILES_RESPONSE, "CNF", "GRU", date(2026, 5, 15))
    assert len(flights) == 1
    f = flights[0]
    assert f.airline == "LATAM"
    assert f.price == 8000.0
    assert f.currency == "MILHAS"
    assert f.miles_program == "LATAM_PASS"
    assert f.departure_time == "07h40"
    assert f.arrival_time == "09h10"
    assert f.is_direct is True


def test_parse_filters_two_stops():
    data = {
        "itineraries": [{
            "price": {"grandTotal": 8000.0},
            "segments": [
                {"departure": {"at": "2026-05-15T07:00:00"}, "arrival": {"at": "2026-05-15T10:00:00"}, "numberOfStops": 0},
                {"departure": {"at": "2026-05-15T11:00:00"}, "arrival": {"at": "2026-05-15T12:00:00"}, "numberOfStops": 0},
                {"departure": {"at": "2026-05-15T13:00:00"}, "arrival": {"at": "2026-05-15T14:00:00"}, "numberOfStops": 0},
            ],
        }]
    }
    searcher = LatamMilesSearcher()
    assert searcher._parse(data, "CNF", "GRU", date(2026, 5, 15)) == []


def test_parse_empty_response():
    searcher = LatamMilesSearcher()
    assert searcher._parse({}, "CNF", "GRU", date(2026, 5, 15)) == []


async def test_search_calls_redemption_true():
    searcher = LatamMilesSearcher()
    mock_response = MagicMock()
    mock_response.json.return_value = SAMPLE_LATAM_MILES_RESPONSE
    mock_response.raise_for_status = MagicMock()

    with patch("airlines.latam_miles.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        flights = await searcher.search("CNF", "GRU", date(2026, 5, 15))

    call_kwargs = mock_client.get.call_args
    params = call_kwargs.kwargs.get("params", call_kwargs.args[1] if len(call_kwargs.args) > 1 else {})
    assert params.get("redemption") == "true"
    assert len(flights) == 1
    assert flights[0].currency == "MILHAS"


async def test_search_returns_empty_on_403():
    searcher = LatamMilesSearcher()
    mock_resp = MagicMock()
    mock_resp.status_code = 403
    err = httpx.HTTPStatusError("403", request=MagicMock(), response=mock_resp)

    with patch("airlines.latam_miles.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=err)
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        flights = await searcher.search("CNF", "GRU", date(2026, 5, 15))

    assert flights == []
```

- [ ] **Step 2: Run to verify failure**

```
pytest tests/test_latam_miles.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'airlines.latam_miles'`

- [ ] **Step 3: Create `airlines/latam_miles.py`**

```python
import asyncio
import logging
from datetime import date
from typing import List

import httpx

from config import REQUEST_TIMEOUT, REQUEST_RETRIES, REQUEST_RETRY_BACKOFF
from airlines.base import Flight, FlightSearcher

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.latamairlines.com/api/v1/flights"
_BOOKING_BASE = "https://www.latamairlines.com/br/pt/oferta-voos"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Accept": "application/json",
    "Referer": "https://www.latamairlines.com/",
}


class LatamMilesSearcher(FlightSearcher):
    AIRLINE_NAME = "LATAM_PASS"

    async def search(self, origin: str, destination: str, departure_date: date) -> List[Flight]:
        params = {
            "origin": origin,
            "destination": destination,
            "outbound": departure_date.strftime("%Y-%m-%d"),
            "adults": 1,
            "cabin": "Economy",
            "redemption": "true",
        }

        for attempt in range(REQUEST_RETRIES):
            try:
                async with httpx.AsyncClient(
                    timeout=REQUEST_TIMEOUT,
                    headers=_HEADERS,
                    follow_redirects=True,
                ) as client:
                    response = await client.get(_BASE_URL, params=params)
                    response.raise_for_status()
                    return self._parse(response.json(), origin, destination, departure_date)
            except httpx.HTTPStatusError as e:
                logger.warning(f"LATAM Pass/{origin}→{destination} {departure_date}: HTTP {e.response.status_code}")
                return []
            except Exception as e:
                logger.warning(f"LATAM Pass/{origin}→{destination} tentativa {attempt + 1}: {e}")
                if attempt < REQUEST_RETRIES - 1:
                    await asyncio.sleep(REQUEST_RETRY_BACKOFF)

        return []

    def _parse(self, data: dict, origin: str, destination: str, departure_date: date) -> List[Flight]:
        flights: List[Flight] = []
        try:
            itineraries = data.get("itineraries", data.get("flights", data.get("offers", [])))
            for it in itineraries:
                price_block = it.get("price", it.get("fare", {}))
                miles = None
                if isinstance(price_block, dict):
                    raw = (
                        price_block.get("grandTotal")
                        or price_block.get("total")
                        or price_block.get("amount")
                    )
                    if raw is not None:
                        miles = int(float(str(raw).replace(",", ".")))
                elif isinstance(price_block, (int, float)):
                    miles = int(price_block)
                if miles is None:
                    continue

                segments = it.get("segments", it.get("legs", []))
                if not segments:
                    continue

                stops = sum(s.get("numberOfStops", 0) for s in segments) + max(0, len(segments) - 1)
                if stops > 1:
                    continue

                first_seg = segments[0]
                last_seg = segments[-1]
                dep_at = first_seg.get("departure", {}).get("at", "") or first_seg.get("departureDateTime", "")
                arr_at = last_seg.get("arrival", {}).get("at", "") or last_seg.get("arrivalDateTime", "")
                dep_time = dep_at[11:16].replace(":", "h") if len(dep_at) >= 16 else ""
                arr_time = arr_at[11:16].replace(":", "h") if len(arr_at) >= 16 else ""

                date_str = departure_date.strftime("%Y-%m-%d")
                booking_url = (
                    f"{_BOOKING_BASE}?origin={origin}&destination={destination}"
                    f"&outbound={date_str}&adults=1&cabin=Economy&redemption=true"
                )

                flights.append(Flight(
                    origin=origin,
                    destination=destination,
                    airline="LATAM",
                    departure_date=departure_date,
                    departure_time=dep_time,
                    arrival_time=arr_time,
                    price=float(miles),
                    is_direct=(stops == 0),
                    stops=stops,
                    booking_url=booking_url,
                    currency="MILHAS",
                    miles_program="LATAM_PASS",
                ))
        except Exception as e:
            logger.error(f"LATAM Pass parse error: {e}")
        return flights
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_latam_miles.py -v
```
Expected: all 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add airlines/latam_miles.py tests/test_latam_miles.py
git commit -m "feat: add LatamMilesSearcher for LATAM Pass monitoring"
```

---

## Task 6: TudoAzul miles searcher

**Files:**
- Create: `airlines/azul_miles.py`
- Create: `tests/test_azul_miles.py`

**Note:** TudoAzul's internal API endpoint needs to be verified before implementing. Step 1 discovers it; Step 3 implements based on what you find. The response structure assumed below may need adjustment.

- [ ] **Step 1: Probe the TudoAzul endpoint**

Run this script from the project root to discover the API:

```python
# probe_tudoazul.py  (run once, then delete)
import httpx, json

# Attempt known endpoint — inspect response
url = "https://www.tudoazul.com.br/api/v1/catalog/flights/availability"
params = {
    "fromCode": "CNF",
    "toCode": "GRU",
    "depDate": "2026-05-20",
    "cabin": "ECONOMY",
    "passengers": 1,
}
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Origin": "https://www.tudoazul.com.br",
    "Referer": "https://www.tudoazul.com.br/",
}

r = httpx.get(url, params=params, headers=headers, timeout=15, follow_redirects=True)
print("Status:", r.status_code)
print("Response:", r.text[:3000])
```

Run: `python probe_tudoazul.py`

If this returns a non-200 or empty response, open https://www.tudoazul.com.br in Chrome, open DevTools → Network, search for a CNF→GRU flight, and look for XHR calls with JSON flight data. Note the URL and response shape, then continue with Step 3 using the actual endpoint and fields.

- [ ] **Step 2: Write failing tests**

Create `tests/test_azul_miles.py` (adjust field names if probe shows different shape):

```python
import pytest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from airlines.azul_miles import AzulMilesSearcher


SAMPLE_TUDOAZUL_RESPONSE = {
    "flights": [
        {
            "departureDate": "2026-05-15",
            "departureTime": "07:40",
            "arrivalTime": "09:10",
            "stops": 0,
            "miles": 9800,
        }
    ]
}


def test_parse_returns_miles_flight():
    searcher = AzulMilesSearcher()
    flights = searcher._parse(SAMPLE_TUDOAZUL_RESPONSE, "CNF", "GRU", date(2026, 5, 15))
    assert len(flights) == 1
    f = flights[0]
    assert f.airline == "AZUL"
    assert f.price == 9800.0
    assert f.currency == "MILHAS"
    assert f.miles_program == "TUDOAZUL"
    assert f.departure_time == "07h40"
    assert f.arrival_time == "09h10"
    assert f.is_direct is True


def test_parse_filters_two_stops():
    data = {"flights": [{"departureDate": "2026-05-15", "departureTime": "07:40",
                          "arrivalTime": "15:00", "stops": 2, "miles": 9800}]}
    searcher = AzulMilesSearcher()
    assert searcher._parse(data, "CNF", "GRU", date(2026, 5, 15)) == []


def test_parse_empty_response():
    searcher = AzulMilesSearcher()
    assert searcher._parse({}, "CNF", "GRU", date(2026, 5, 15)) == []


async def test_search_returns_miles_flights():
    searcher = AzulMilesSearcher()
    mock_response = MagicMock()
    mock_response.json.return_value = SAMPLE_TUDOAZUL_RESPONSE
    mock_response.raise_for_status = MagicMock()

    with patch("airlines.azul_miles.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        flights = await searcher.search("CNF", "GRU", date(2026, 5, 15))

    assert len(flights) == 1
    assert flights[0].currency == "MILHAS"
    assert flights[0].miles_program == "TUDOAZUL"


async def test_search_returns_empty_on_error():
    searcher = AzulMilesSearcher()
    mock_resp = MagicMock()
    mock_resp.status_code = 403
    err = httpx.HTTPStatusError("403", request=MagicMock(), response=mock_resp)

    with patch("airlines.azul_miles.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=err)
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        flights = await searcher.search("CNF", "GRU", date(2026, 5, 15))

    assert flights == []
```

- [ ] **Step 3: Run to verify failure**

```
pytest tests/test_azul_miles.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'airlines.azul_miles'`

- [ ] **Step 4: Create `airlines/azul_miles.py`**

Adjust `_BASE_URL` and `_parse` field names based on probe findings from Step 1:

```python
import asyncio
import logging
from datetime import date
from typing import List

import httpx

from config import REQUEST_TIMEOUT, REQUEST_RETRIES, REQUEST_RETRY_BACKOFF
from airlines.base import Flight, FlightSearcher

logger = logging.getLogger(__name__)

# Verify this URL against probe findings — adjust if endpoint differs
_BASE_URL = "https://www.tudoazul.com.br/api/v1/catalog/flights/availability"
_BOOKING_BASE = "https://www.tudoazul.com.br/emissao"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Origin": "https://www.tudoazul.com.br",
    "Referer": "https://www.tudoazul.com.br/",
}


class AzulMilesSearcher(FlightSearcher):
    AIRLINE_NAME = "TUDOAZUL"

    async def search(self, origin: str, destination: str, departure_date: date) -> List[Flight]:
        params = {
            "fromCode": origin,
            "toCode": destination,
            "depDate": departure_date.strftime("%Y-%m-%d"),
            "cabin": "ECONOMY",
            "passengers": 1,
        }

        for attempt in range(REQUEST_RETRIES):
            try:
                async with httpx.AsyncClient(
                    timeout=REQUEST_TIMEOUT,
                    headers=_HEADERS,
                    follow_redirects=True,
                ) as client:
                    response = await client.get(_BASE_URL, params=params)
                    response.raise_for_status()
                    return self._parse(response.json(), origin, destination, departure_date)
            except httpx.HTTPStatusError as e:
                logger.warning(f"TudoAzul/{origin}→{destination} {departure_date}: HTTP {e.response.status_code}")
                return []
            except Exception as e:
                logger.warning(f"TudoAzul/{origin}→{destination} tentativa {attempt + 1}: {e}")
                if attempt < REQUEST_RETRIES - 1:
                    await asyncio.sleep(REQUEST_RETRY_BACKOFF)

        return []

    def _parse(self, data: dict, origin: str, destination: str, departure_date: date) -> List[Flight]:
        # Field names here match the assumed probe response — adjust if needed
        flights: List[Flight] = []
        try:
            for f in data.get("flights", []):
                stops = f.get("stops", 0)
                if stops > 1:
                    continue
                miles = f.get("miles")
                if miles is None:
                    continue

                dep_time = f.get("departureTime", "").replace(":", "h")
                arr_time = f.get("arrivalTime", "").replace(":", "h")
                date_str = departure_date.strftime("%Y-%m-%d")
                booking_url = (
                    f"{_BOOKING_BASE}?fromCode={origin}&toCode={destination}"
                    f"&depDate={date_str}&cabin=ECONOMY&passengers=1"
                )

                flights.append(Flight(
                    origin=origin,
                    destination=destination,
                    airline="AZUL",
                    departure_date=departure_date,
                    departure_time=dep_time,
                    arrival_time=arr_time,
                    price=float(miles),
                    is_direct=(stops == 0),
                    stops=stops,
                    booking_url=booking_url,
                    currency="MILHAS",
                    miles_program="TUDOAZUL",
                ))
        except Exception as e:
            logger.error(f"TudoAzul parse error: {e}")
        return flights
```

- [ ] **Step 5: Run tests**

```
pytest tests/test_azul_miles.py -v
```
Expected: all 5 tests PASS

- [ ] **Step 6: Commit**

```bash
git add airlines/azul_miles.py tests/test_azul_miles.py
git commit -m "feat: add AzulMilesSearcher for TudoAzul monitoring"
```

---

## Task 7: Update Telegram alert format

**Files:**
- Modify: `telegram_bot.py`
- Modify: `tests/test_telegram_bot.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_telegram_bot.py`:

```python
def _miles_flight(miles: float = 8500.0, program: str = "SMILES") -> Flight:
    return Flight(
        origin="CNF",
        destination="GRU",
        airline="GOL",
        departure_date=date(2026, 5, 15),
        departure_time="07h40",
        arrival_time="09h10",
        price=miles,
        is_direct=True,
        stops=0,
        booking_url="https://example.com/redeem",
        currency="MILHAS",
        miles_program=program,
    )


def test_format_miles_alert_contains_milhas_header():
    msg = telegram_bot.format_alert(_miles_flight())
    assert "MILHAS BARATAS" in msg


def test_format_miles_alert_contains_points_value():
    msg = telegram_bot.format_alert(_miles_flight(8500.0))
    assert "8.500" in msg


def test_format_miles_alert_contains_smiles_label():
    msg = telegram_bot.format_alert(_miles_flight(program="SMILES"))
    assert "Smiles" in msg


def test_format_miles_alert_contains_latam_pass_label():
    msg = telegram_bot.format_alert(_miles_flight(program="LATAM_PASS"))
    assert "LATAM Pass" in msg


def test_format_miles_alert_contains_tudoazul_label():
    msg = telegram_bot.format_alert(_miles_flight(program="TUDOAZUL"))
    assert "TudoAzul" in msg


def test_format_cash_alert_unchanged():
    msg = telegram_bot.format_alert(_sample_flight())
    assert "PASSAGEM BARATA" in msg
    assert "R$" in msg or "289,90" in msg
```

- [ ] **Step 2: Run to verify failure**

```
pytest tests/test_telegram_bot.py -v
```
Expected: 6 new tests FAIL (`MILHAS BARATAS not found` etc)

- [ ] **Step 3: Update `telegram_bot.py`**

Replace `format_alert`:

```python
import logging
from datetime import datetime

from telegram import Bot, LinkPreviewOptions
from telegram.constants import ParseMode

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID
from airlines.base import Flight

logger = logging.getLogger(__name__)

_bot: Bot | None = None

_MILES_PROGRAM_LABELS = {
    "SMILES":     "Smiles",
    "LATAM_PASS": "LATAM Pass",
    "TUDOAZUL":   "TudoAzul",
}


def get_bot() -> Bot:
    global _bot
    if _bot is None:
        _bot = Bot(token=TELEGRAM_BOT_TOKEN)
    return _bot


def format_alert(flight: Flight) -> str:
    dep_date = flight.departure_date.strftime("%d/%m/%Y")
    stops_str = "Direto" if flight.is_direct else f"{flight.stops} parada"
    now_str = datetime.now().strftime("%H:%M")

    if flight.currency == "MILHAS":
        program_label = _MILES_PROGRAM_LABELS.get(flight.miles_program, flight.miles_program)
        miles_str = f"{int(flight.price):,}".replace(",", ".")
        return (
            f"🎯 *MILHAS BARATAS DETECTADAS*\n\n"
            f"🛫 {flight.origin} → {flight.destination}\n"
            f"🏆 {miles_str} pontos {program_label}\n"
            f"📅 {dep_date} • {flight.departure_time} → {flight.arrival_time}\n"
            f"🏢 {flight.airline} • {stops_str}\n"
            f"🔗 [Resgatar agora]({flight.booking_url})\n\n"
            f"⏰ Detectado às {now_str}"
        )

    price_str = f"R$ {flight.price:_.2f}".replace("_", "X").replace(".", ",").replace("X", ".")
    return (
        f"✈️ *PASSAGEM BARATA DETECTADA*\n\n"
        f"🛫 {flight.origin} → {flight.destination}\n"
        f"💰 {price_str}\n"
        f"📅 {dep_date} • {flight.departure_time} → {flight.arrival_time}\n"
        f"🏢 {flight.airline} • {stops_str}\n"
        f"🔗 [Reservar agora]({flight.booking_url})\n\n"
        f"⏰ Detectado às {now_str}"
    )


async def send_alert(flight: Flight) -> None:
    bot = get_bot()
    message = format_alert(flight)
    try:
        await bot.send_message(
            chat_id=TELEGRAM_CHANNEL_ID,
            text=message,
            parse_mode=ParseMode.MARKDOWN,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
        logger.info(
            f"Alerta enviado: {flight.airline}/{flight.origin}→{flight.destination} "
            f"{flight.price:.0f} {flight.currency} {flight.departure_date}"
        )
    except Exception as e:
        logger.error(f"Falha ao enviar alerta Telegram: {e}")
```

- [ ] **Step 4: Run all telegram tests**

```
pytest tests/test_telegram_bot.py -v
```
Expected: all tests PASS (existing + 6 new)

- [ ] **Step 5: Commit**

```bash
git add telegram_bot.py tests/test_telegram_bot.py
git commit -m "feat: add miles alert format to telegram_bot"
```

---

## Task 8: Rewrite scheduler

**Files:**
- Modify: `scheduler.py`
- Modify: `tests/test_scheduler.py`

- [ ] **Step 1: Write failing tests**

Replace `tests/test_scheduler.py` entirely:

```python
import pytest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from airlines.base import Flight


def _flight(price: float, airline: str = "GOL", currency: str = "BRL", miles_program: str = "") -> Flight:
    return Flight(
        origin="CNF", destination="GRU", airline=airline,
        departure_date=date(2026, 5, 15), departure_time="07h40",
        arrival_time="09h10", price=price, is_direct=True, stops=0,
        booking_url="https://example.com",
        currency=currency, miles_program=miles_program,
    )


async def test_cash_cycle_sends_alert_for_cheap_date(monkeypatch):
    import scheduler
    import cache
    import telegram_bot

    cheap_flight = _flight(price=289.90)

    mock_searcher = MagicMock()
    mock_searcher.scan_dates = AsyncMock(return_value=[(date(2026, 5, 15), 289.90)])
    mock_searcher.search = AsyncMock(return_value=[cheap_flight])

    monkeypatch.setattr(scheduler, "AMADEUS_SEARCHERS", {"GOL": mock_searcher})
    monkeypatch.setattr(scheduler, "google_searcher", MagicMock(search_range=AsyncMock(return_value=[])))
    monkeypatch.setattr(cache, "purge_expired", AsyncMock())
    monkeypatch.setattr(cache, "is_cached", AsyncMock(return_value=False))
    monkeypatch.setattr(cache, "save_to_cache", AsyncMock())
    monkeypatch.setattr(telegram_bot, "send_alert", AsyncMock())
    monkeypatch.setattr(scheduler, "ROUTES", [
        {"from": "CNF", "to": "GRU", "threshold": 350, "airlines": ["GOL"]}
    ])

    await scheduler.cash_cycle()

    telegram_bot.send_alert.assert_called_once_with(cheap_flight)


async def test_cash_cycle_skips_dates_above_threshold(monkeypatch):
    import scheduler
    import cache
    import telegram_bot

    mock_searcher = MagicMock()
    mock_searcher.scan_dates = AsyncMock(return_value=[(date(2026, 5, 15), 500.00)])

    monkeypatch.setattr(scheduler, "AMADEUS_SEARCHERS", {"GOL": mock_searcher})
    monkeypatch.setattr(scheduler, "google_searcher", MagicMock(search_range=AsyncMock(return_value=[])))
    monkeypatch.setattr(cache, "purge_expired", AsyncMock())
    monkeypatch.setattr(telegram_bot, "send_alert", AsyncMock())
    monkeypatch.setattr(scheduler, "ROUTES", [
        {"from": "CNF", "to": "GRU", "threshold": 350, "airlines": ["GOL"]}
    ])

    await scheduler.cash_cycle()

    mock_searcher.search.assert_not_called()
    telegram_bot.send_alert.assert_not_called()


async def test_cash_cycle_falls_back_to_google_when_scan_empty(monkeypatch):
    import scheduler
    import cache
    import telegram_bot

    cheap_gol = _flight(price=289.90, airline="GOL Linhas Aéreas")

    mock_searcher = MagicMock()
    mock_searcher.scan_dates = AsyncMock(return_value=[])

    monkeypatch.setattr(scheduler, "AMADEUS_SEARCHERS", {"GOL": mock_searcher})
    monkeypatch.setattr(scheduler, "google_searcher",
        MagicMock(search_range=AsyncMock(return_value=[cheap_gol])))
    monkeypatch.setattr(cache, "purge_expired", AsyncMock())
    monkeypatch.setattr(cache, "is_cached", AsyncMock(return_value=False))
    monkeypatch.setattr(cache, "save_to_cache", AsyncMock())
    monkeypatch.setattr(telegram_bot, "send_alert", AsyncMock())
    monkeypatch.setattr(scheduler, "ROUTES", [
        {"from": "CNF", "to": "GRU", "threshold": 350, "airlines": ["GOL"]}
    ])

    await scheduler.cash_cycle()

    telegram_bot.send_alert.assert_called_once_with(cheap_gol)


async def test_cash_cycle_skips_cached(monkeypatch):
    import scheduler
    import cache
    import telegram_bot

    cheap_flight = _flight(price=289.90)
    mock_searcher = MagicMock()
    mock_searcher.scan_dates = AsyncMock(return_value=[(date(2026, 5, 15), 289.90)])
    mock_searcher.search = AsyncMock(return_value=[cheap_flight])

    monkeypatch.setattr(scheduler, "AMADEUS_SEARCHERS", {"GOL": mock_searcher})
    monkeypatch.setattr(scheduler, "google_searcher", MagicMock(search_range=AsyncMock(return_value=[])))
    monkeypatch.setattr(cache, "purge_expired", AsyncMock())
    monkeypatch.setattr(cache, "is_cached", AsyncMock(return_value=True))
    monkeypatch.setattr(cache, "save_to_cache", AsyncMock())
    monkeypatch.setattr(telegram_bot, "send_alert", AsyncMock())
    monkeypatch.setattr(scheduler, "ROUTES", [
        {"from": "CNF", "to": "GRU", "threshold": 350, "airlines": ["GOL"]}
    ])

    await scheduler.cash_cycle()
    telegram_bot.send_alert.assert_not_called()


async def test_miles_cycle_sends_alert_below_threshold(monkeypatch):
    import scheduler
    import cache
    import telegram_bot

    cheap_miles = _flight(price=8500.0, airline="GOL", currency="MILHAS", miles_program="SMILES")

    mock_smiles = MagicMock(search_range=AsyncMock(return_value=[cheap_miles]))
    mock_latam  = MagicMock(search_range=AsyncMock(return_value=[]))
    mock_azul   = MagicMock(search_range=AsyncMock(return_value=[]))

    monkeypatch.setattr(scheduler, "MILES_SEARCHERS", {
        "SMILES": mock_smiles,
        "LATAM_PASS": mock_latam,
        "TUDOAZUL": mock_azul,
    })
    monkeypatch.setattr(cache, "purge_expired", AsyncMock())
    monkeypatch.setattr(cache, "is_cached", AsyncMock(return_value=False))
    monkeypatch.setattr(cache, "save_to_cache", AsyncMock())
    monkeypatch.setattr(telegram_bot, "send_alert", AsyncMock())
    monkeypatch.setattr(scheduler, "MILES_ROUTES", [
        {"from": "CNF", "to": "GRU", "thresholds": {"SMILES": 10000, "LATAM_PASS": 10000, "TUDOAZUL": 14000}}
    ])

    await scheduler.miles_cycle()
    telegram_bot.send_alert.assert_called_once_with(cheap_miles)


async def test_miles_cycle_skips_above_threshold(monkeypatch):
    import scheduler
    import cache
    import telegram_bot

    expensive_miles = _flight(price=15000.0, airline="GOL", currency="MILHAS", miles_program="SMILES")

    mock_smiles = MagicMock(search_range=AsyncMock(return_value=[expensive_miles]))
    mock_latam  = MagicMock(search_range=AsyncMock(return_value=[]))
    mock_azul   = MagicMock(search_range=AsyncMock(return_value=[]))

    monkeypatch.setattr(scheduler, "MILES_SEARCHERS", {
        "SMILES": mock_smiles, "LATAM_PASS": mock_latam, "TUDOAZUL": mock_azul,
    })
    monkeypatch.setattr(cache, "purge_expired", AsyncMock())
    monkeypatch.setattr(telegram_bot, "send_alert", AsyncMock())
    monkeypatch.setattr(scheduler, "MILES_ROUTES", [
        {"from": "CNF", "to": "GRU", "thresholds": {"SMILES": 10000, "LATAM_PASS": 10000, "TUDOAZUL": 14000}}
    ])

    await scheduler.miles_cycle()
    telegram_bot.send_alert.assert_not_called()


async def test_run_cycle_calls_both_cycles(monkeypatch):
    import scheduler

    monkeypatch.setattr(scheduler, "cash_cycle", AsyncMock())
    monkeypatch.setattr(scheduler, "miles_cycle", AsyncMock())

    await scheduler.run_cycle()

    scheduler.cash_cycle.assert_called_once()
    scheduler.miles_cycle.assert_called_once()
```

- [ ] **Step 2: Run to verify failure**

```
pytest tests/test_scheduler.py -v
```
Expected: FAIL — `cash_cycle`, `miles_cycle` not found in scheduler

- [ ] **Step 3: Rewrite `scheduler.py`**

```python
import asyncio
import logging
import time
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

import cache
import telegram_bot
from airlines.amadeus import AmadeusSearcher
from airlines.smiles import SmilesSearcher
from airlines.latam_miles import LatamMilesSearcher
from airlines.azul_miles import AzulMilesSearcher
from airlines.google_flights import GoogleFlightsSearcher
from config import ROUTES, MILES_ROUTES, CYCLE_MINUTES, CACHE_TTL_HOURS, SEARCH_DAYS_AHEAD, BATCH_SIZE

logger = logging.getLogger(__name__)

AMADEUS_SEARCHERS: dict[str, AmadeusSearcher] = {
    "GOL":   AmadeusSearcher("GOL"),
    "LATAM": AmadeusSearcher("LATAM"),
    "AZUL":  AmadeusSearcher("AZUL"),
}

MILES_SEARCHERS = {
    "SMILES":     SmilesSearcher(),
    "LATAM_PASS": LatamMilesSearcher(),
    "TUDOAZUL":   AzulMilesSearcher(),
}

google_searcher = GoogleFlightsSearcher()

_AIRLINE_ALIASES: dict[str, list[str]] = {
    "GOL":   ["gol"],
    "LATAM": ["latam"],
    "AZUL":  ["azul"],
}


def _matches_airline(flight_airline: str, expected: str) -> bool:
    aliases = _AIRLINE_ALIASES.get(expected.upper(), [expected.lower()])
    return any(alias in flight_airline.lower() for alias in aliases)


async def cash_cycle() -> None:
    _gf_cache: dict[tuple, list] = {}

    for route in ROUTES:
        origin = route["from"]
        dest = route["to"]
        threshold = route["threshold"]

        for airline_name in route["airlines"]:
            if airline_name not in AMADEUS_SEARCHERS:
                continue
            searcher = AMADEUS_SEARCHERS[airline_name]

            cheap_dates = await searcher.scan_dates(origin, dest, SEARCH_DAYS_AHEAD)
            cheap_dates = [(d, p) for d, p in cheap_dates if p < threshold]

            if not cheap_dates:
                logger.info(f"{airline_name}/{origin}→{dest}: sem datas baratas no Amadeus, tentando Google Flights")
                key = (origin, dest)
                if key not in _gf_cache:
                    try:
                        _gf_cache[key] = await google_searcher.search_range(origin, dest, SEARCH_DAYS_AHEAD, BATCH_SIZE)
                    except Exception as e:
                        logger.warning(f"{airline_name}/{origin}→{dest}: Google Flights falhou: {e}")
                        _gf_cache[key] = []
                gf_flights = [f for f in _gf_cache[key] if _matches_airline(f.airline, airline_name)]
                below = [f for f in gf_flights if f.price < threshold and f.stops <= 1]
                for flight in below:
                    if not await cache.is_cached(flight):
                        await telegram_bot.send_alert(flight)
                        await cache.save_to_cache(flight, CACHE_TTL_HOURS)
                continue

            detail_tasks = [searcher.search(origin, dest, d) for d, _ in cheap_dates]
            results = await asyncio.gather(*detail_tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, Exception) or not result:
                    continue
                for flight in result:
                    if flight.price < threshold and flight.stops <= 1:
                        if not await cache.is_cached(flight):
                            await telegram_bot.send_alert(flight)
                            await cache.save_to_cache(flight, CACHE_TTL_HOURS)


async def miles_cycle() -> None:
    for route in MILES_ROUTES:
        origin = route["from"]
        dest = route["to"]
        thresholds = route["thresholds"]

        tasks = {
            program: searcher.search_range(origin, dest, SEARCH_DAYS_AHEAD, BATCH_SIZE)
            for program, searcher in MILES_SEARCHERS.items()
        }
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        results_by_program = dict(zip(tasks.keys(), results))

        for program, flights in results_by_program.items():
            if isinstance(flights, Exception):
                logger.warning(f"{program}/{origin}→{dest}: {flights}")
                continue
            threshold = thresholds.get(program, 0)
            for flight in flights:
                if flight.price < threshold:
                    if not await cache.is_cached(flight):
                        await telegram_bot.send_alert(flight)
                        await cache.save_to_cache(flight, CACHE_TTL_HOURS)


async def run_cycle() -> None:
    start = time.monotonic()
    await cache.purge_expired()
    await asyncio.gather(cash_cycle(), miles_cycle())
    elapsed = time.monotonic() - start
    logger.info(f"CICLO CONCLUÍDO — {elapsed:.0f}s")


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

- [ ] **Step 4: Run all scheduler tests**

```
pytest tests/test_scheduler.py -v
```
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add scheduler.py tests/test_scheduler.py
git commit -m "feat: rewrite scheduler with cash_cycle (Amadeus) + miles_cycle"
```

---

## Task 9: Delete old files and run full suite

**Files:**
- Delete: `airlines/gol.py`, `airlines/latam.py`, `airlines/azul.py`
- Delete: `tests/test_gol.py`, `tests/test_latam.py`, `tests/test_azul.py`
- Delete: `test_apis.py` (root-level probe script)

- [ ] **Step 1: Delete old airline scrapers and their tests**

```bash
git rm airlines/gol.py airlines/latam.py airlines/azul.py
git rm tests/test_gol.py tests/test_latam.py tests/test_azul.py
git rm test_apis.py
```

- [ ] **Step 2: Run full test suite**

```
pytest -v
```
Expected: all tests PASS, no import errors for deleted modules

- [ ] **Step 3: Commit**

```bash
git commit -m "chore: remove broken airline scrapers replaced by Amadeus + miles searchers"
```

---

## Task 10: Smoke test end-to-end

- [ ] **Step 1: Verify Amadeus credentials work**

Run this one-off script from the project root:

```python
# smoke_amadeus.py  (run once, then delete)
import asyncio
from airlines.amadeus import AmadeusSearcher

async def main():
    s = AmadeusSearcher("GOL")
    dates = await s.scan_dates("CNF", "GRU", days_ahead=30)
    print("Dates found:", len(dates))
    if dates:
        cheapest_date, price = min(dates, key=lambda x: x[1])
        print(f"Cheapest: {cheapest_date} R$ {price:.2f}")
        flights = await s.search("CNF", "GRU", cheapest_date)
        print(f"Flights for that date: {len(flights)}")
        if flights:
            print(flights[0])

asyncio.run(main())
```

Run: `python smoke_amadeus.py`
Expected: prints found dates and at least one flight object

- [ ] **Step 2: Verify Smiles miles endpoint**

```python
# smoke_smiles.py  (run once, then delete)
import asyncio
from datetime import date, timedelta
from airlines.smiles import SmilesSearcher

async def main():
    s = SmilesSearcher()
    target = date.today() + timedelta(days=30)
    flights = await s.search("CNF", "GRU", target)
    print(f"Smiles flights: {len(flights)}")
    if flights:
        print(flights[0])

asyncio.run(main())
```

Run: `python smoke_smiles.py`

If you get 0 results with no error, inspect the raw response by temporarily adding `print(response.json())` before the `return self._parse(...)` line in `airlines/smiles.py`. Adjust field names in `_parse` accordingly, re-run tests, commit the fix.

- [ ] **Step 3: Start the bot and observe one full cycle**

```
python main.py
```

Watch for log lines like:
```
CICLO INICIADO
GOL/CNF→GRU: sem datas baratas ...  (or alert sent)
SMILES/CNF→GRU: X voos encontrados ...
CICLO CONCLUÍDO — Xs
```

- [ ] **Step 4: Final commit if any probe scripts were left behind**

```bash
git status  # confirm no stray probe scripts committed
```
