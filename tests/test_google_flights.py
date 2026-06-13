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

def test_parse_price_dot_thousands():
    assert _parse_price("R$1.290") == 1290.0


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


def test_parse_keeps_multi_stop_flights():
    # Stops are no longer filtered — a 2-stop flight is kept (the Azul comparison
    # ignores stops so long international routes can fire).
    searcher = GoogleFlightsSearcher()
    result = _make_ff_result([_make_ff_flight(stops=2)])
    flights = searcher._parse(result, "GRU", "CGH", date(2026, 5, 15))
    assert len(flights) == 1
    assert flights[0].stops == 2
    assert flights[0].is_direct is False


def test_parse_handles_unknown_stops_without_aborting():
    # fast_flights sometimes returns stops='Unknown'; it must not crash the parse
    # nor drop the other flights in the same response.
    searcher = GoogleFlightsSearcher()
    result = _make_ff_result([
        _make_ff_flight(name="Azul", stops="Unknown", price="R$300"),
        _make_ff_flight(name="LATAM", stops=0, price="R$400"),
    ])
    flights = searcher._parse(result, "CNF", "SSA", date(2026, 7, 15))
    assert len(flights) == 2
    assert {f.airline for f in flights} == {"Azul", "LATAM"}


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
