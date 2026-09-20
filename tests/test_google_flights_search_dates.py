"""search_dates retries the dates that failed at the END of the route, so a batch never
waits for one member's backoff."""
import logging
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from airlines import google_flights
from airlines.google_flights import GoogleFlightsSearcher

DAYS = [date(2026, 12, 1) + timedelta(days=i) for i in range(5)]
GOOD = SimpleNamespace(flights=[SimpleNamespace(
    name="Azul", price="R$300", stops=0, departure="7:40 AM", arrival="9:00 AM")])


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    slept: list[float] = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(google_flights.asyncio, "sleep", fake_sleep)
    return slept


def _fetch(monkeypatch, outcome_for):
    """Patch the blocking fetch; `outcome_for(day, nth_call_for_that_day)` returns a result
    object or raises."""
    seen: dict[str, int] = {}

    def fake_fetch(tfs, **kwargs):
        day = tfs.flight_data[0].date
        seen[day] = seen.get(day, 0) + 1
        return outcome_for(day, seen[day])

    monkeypatch.setattr(google_flights, "get_flights_from_filter", fake_fetch)
    return seen


async def test_a_date_that_fails_once_is_recovered_with_one_sleep_for_the_route(
        monkeypatch, no_real_sleep):
    failing = {DAYS[0].isoformat(), DAYS[3].isoformat()}

    def outcome(day, nth):
        if day in failing and nth == 1:
            raise OSError("os error 101")
        return GOOD

    _fetch(monkeypatch, outcome)
    s = GoogleFlightsSearcher()
    flights = await s.search_dates("CNF", "GIG", DAYS, batch_size=7)

    assert len(flights) == len(DAYS)                 # every date answered, none duplicated
    assert no_real_sleep == [1.0]                    # one sleep for two failed dates
    assert (s.queries, s.failures) == (len(DAYS), 0)


async def test_a_date_that_always_fails_is_counted_once_with_one_warning(monkeypatch, caplog):
    def outcome(day, nth):
        if day == DAYS[2].isoformat():
            raise OSError("os error 101")
        return GOOD

    seen = _fetch(monkeypatch, outcome)
    s = GoogleFlightsSearcher()
    with caplog.at_level(logging.DEBUG):
        flights = await s.search_dates("CNF", "GIG", DAYS, batch_size=2)

    assert seen[DAYS[2].isoformat()] == google_flights.MAX_RETRIES + 1
    assert len(flights) == len(DAYS) - 1
    assert (s.queries, s.failures) == (len(DAYS), 1)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1 and "1 data(s) falharam" in warnings[0].getMessage()


async def test_no_flights_found_is_never_retried(monkeypatch, no_real_sleep):
    def outcome(day, nth):
        if day == DAYS[1].isoformat():
            raise RuntimeError("No flights found:\n" + "page text " * 500)
        return GOOD

    seen = _fetch(monkeypatch, outcome)
    s = GoogleFlightsSearcher()
    flights = await s.search_dates("CNF", "FTE", DAYS, batch_size=7)

    assert seen[DAYS[1].isoformat()] == 1
    assert no_real_sleep == []
    assert (s.queries, s.failures, s.no_flights) == (len(DAYS), 0, 1)
    assert len(flights) == len(DAYS) - 1


async def test_a_clean_route_never_sleeps(monkeypatch, no_real_sleep):
    _fetch(monkeypatch, lambda day, nth: GOOD)
    s = GoogleFlightsSearcher()
    flights = await s.search_dates("CNF", "GIG", DAYS, batch_size=2)

    assert len(flights) == len(DAYS)
    assert no_real_sleep == []
    assert (s.queries, s.failures) == (len(DAYS), 0)


async def test_an_empty_date_list_costs_nothing(monkeypatch, no_real_sleep):
    _fetch(monkeypatch, lambda day, nth: GOOD)
    s = GoogleFlightsSearcher()
    assert await s.search_dates("CNF", "GIG", []) == []
    assert (s.queries, s.failures) == (0, 0)
    assert no_real_sleep == []
