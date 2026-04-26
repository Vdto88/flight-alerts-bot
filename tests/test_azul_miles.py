import json
import pytest
from datetime import date
from pathlib import Path

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "azul_miles_sample.json").read_text())


def test_parse_extracts_available_fares():
    from airlines.azul_miles import AzulMilesSearcher
    searcher = AzulMilesSearcher()
    flights = searcher._parse(FIXTURE, "CNF", "IGU", date(2026, 7, 15))
    # Flight 1 has 2 available fares; Flight 2 has 1 fare with available=false (skipped)
    assert len(flights) == 2


def test_parse_miles_values():
    from airlines.azul_miles import AzulMilesSearcher
    searcher = AzulMilesSearcher()
    flights = searcher._parse(FIXTURE, "CNF", "IGU", date(2026, 7, 15))
    miles_list = sorted(f.miles for f in flights)
    assert miles_list == [18000, 20000]


def test_parse_price_is_zero():
    from airlines.azul_miles import AzulMilesSearcher
    searcher = AzulMilesSearcher()
    flights = searcher._parse(FIXTURE, "CNF", "IGU", date(2026, 7, 15))
    assert all(f.price == 0.0 for f in flights)


def test_parse_is_miles_flight():
    from airlines.azul_miles import AzulMilesSearcher
    searcher = AzulMilesSearcher()
    flights = searcher._parse(FIXTURE, "CNF", "IGU", date(2026, 7, 15))
    assert all(f.is_miles_flight for f in flights)


def test_parse_airline_name():
    from airlines.azul_miles import AzulMilesSearcher
    searcher = AzulMilesSearcher()
    flights = searcher._parse(FIXTURE, "CNF", "IGU", date(2026, 7, 15))
    assert all(f.airline == "AZUL_MILES" for f in flights)


def test_parse_skips_unavailable_fares():
    from airlines.azul_miles import AzulMilesSearcher
    searcher = AzulMilesSearcher()
    flights = searcher._parse(FIXTURE, "CNF", "IGU", date(2026, 7, 15))
    miles_values = [f.miles for f in flights]
    assert 25000 not in miles_values


def test_parse_departure_time():
    from airlines.azul_miles import AzulMilesSearcher
    searcher = AzulMilesSearcher()
    flights = searcher._parse(FIXTURE, "CNF", "IGU", date(2026, 7, 15))
    first = next(f for f in flights if f.miles == 20000)
    assert first.departure_time == "07:40"


def test_parse_is_direct():
    from airlines.azul_miles import AzulMilesSearcher
    searcher = AzulMilesSearcher()
    flights = searcher._parse(FIXTURE, "CNF", "IGU", date(2026, 7, 15))
    assert all(f.is_direct for f in flights)
    assert all(f.stops == 0 for f in flights)


def test_parse_empty_response():
    from airlines.azul_miles import AzulMilesSearcher
    searcher = AzulMilesSearcher()
    flights = searcher._parse({}, "CNF", "IGU", date(2026, 7, 15))
    assert flights == []


def test_parse_missing_flights_key():
    from airlines.azul_miles import AzulMilesSearcher
    searcher = AzulMilesSearcher()
    flights = searcher._parse({"otherKey": []}, "CNF", "IGU", date(2026, 7, 15))
    assert flights == []


def test_parse_taxes_brl_is_none():
    from airlines.azul_miles import AzulMilesSearcher
    searcher = AzulMilesSearcher()
    flights = searcher._parse(FIXTURE, "CNF", "IGU", date(2026, 7, 15))
    assert all(f.taxes_brl is None for f in flights)


def test_search_date_returns_empty():
    """_search_date is blocked — must always return []."""
    import asyncio
    from unittest.mock import MagicMock
    from airlines.azul_miles import AzulMilesSearcher
    searcher = AzulMilesSearcher()
    result = asyncio.run(
        searcher._search_date(MagicMock(), "CNF", "IGU", date(2026, 7, 15))
    )
    assert result == []
