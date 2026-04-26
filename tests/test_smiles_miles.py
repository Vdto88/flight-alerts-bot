import json
import pytest
from datetime import date
from pathlib import Path

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "smiles_sample.json").read_text())


def test_parse_extracts_available_fares():
    from airlines.smiles_miles import SmilesMilesSearcher
    searcher = SmilesMilesSearcher()
    flights = searcher._parse(FIXTURE, "CNF", "IGU", date(2026, 7, 15))
    # 2 fares with quantity>0 (third has quantity=0 and is skipped)
    assert len(flights) == 2


def test_parse_miles_values():
    from airlines.smiles_miles import SmilesMilesSearcher
    searcher = SmilesMilesSearcher()
    flights = searcher._parse(FIXTURE, "CNF", "IGU", date(2026, 7, 15))
    miles_list = sorted(f.miles for f in flights)
    assert miles_list == [12000, 15000]


def test_parse_price_is_zero():
    from airlines.smiles_miles import SmilesMilesSearcher
    searcher = SmilesMilesSearcher()
    flights = searcher._parse(FIXTURE, "CNF", "IGU", date(2026, 7, 15))
    assert all(f.price == 0.0 for f in flights)


def test_parse_is_miles_flight():
    from airlines.smiles_miles import SmilesMilesSearcher
    searcher = SmilesMilesSearcher()
    flights = searcher._parse(FIXTURE, "CNF", "IGU", date(2026, 7, 15))
    assert all(f.is_miles_flight for f in flights)


def test_parse_airline_name():
    from airlines.smiles_miles import SmilesMilesSearcher
    searcher = SmilesMilesSearcher()
    flights = searcher._parse(FIXTURE, "CNF", "IGU", date(2026, 7, 15))
    assert all(f.airline == "SMILES" for f in flights)


def test_parse_skips_zero_quantity():
    from airlines.smiles_miles import SmilesMilesSearcher
    searcher = SmilesMilesSearcher()
    flights = searcher._parse(FIXTURE, "CNF", "IGU", date(2026, 7, 15))
    miles_values = [f.miles for f in flights]
    assert 20000 not in miles_values


def test_parse_departure_time():
    from airlines.smiles_miles import SmilesMilesSearcher
    searcher = SmilesMilesSearcher()
    flights = searcher._parse(FIXTURE, "CNF", "IGU", date(2026, 7, 15))
    # First flight departs 07:40
    first = next(f for f in flights if f.miles == 15000)
    assert first.departure_time == "07h40"


def test_parse_is_direct():
    from airlines.smiles_miles import SmilesMilesSearcher
    searcher = SmilesMilesSearcher()
    flights = searcher._parse(FIXTURE, "CNF", "IGU", date(2026, 7, 15))
    assert all(f.is_direct for f in flights)
    assert all(f.stops == 0 for f in flights)


def test_parse_empty_response():
    from airlines.smiles_miles import SmilesMilesSearcher
    searcher = SmilesMilesSearcher()
    flights = searcher._parse({}, "CNF", "IGU", date(2026, 7, 15))
    assert flights == []


def test_parse_missing_segment_list():
    from airlines.smiles_miles import SmilesMilesSearcher
    searcher = SmilesMilesSearcher()
    flights = searcher._parse({"otherKey": []}, "CNF", "IGU", date(2026, 7, 15))
    assert flights == []


def test_parse_taxes_brl_is_none():
    from airlines.smiles_miles import SmilesMilesSearcher
    searcher = SmilesMilesSearcher()
    flights = searcher._parse(FIXTURE, "CNF", "IGU", date(2026, 7, 15))
    assert all(f.taxes_brl is None for f in flights)
