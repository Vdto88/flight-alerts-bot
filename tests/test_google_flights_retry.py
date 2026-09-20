import logging
from datetime import date
from types import SimpleNamespace

import pytest

from airlines import google_flights
from airlines.google_flights import GoogleFlightsSearcher

DAY = date(2026, 12, 1)
GOOD = SimpleNamespace(flights=[SimpleNamespace(
    name="Azul", price="R$300", stops=0, departure="7:40 AM", arrival="9:00 AM")])


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    slept: list[float] = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(google_flights.asyncio, "sleep", fake_sleep)
    return slept


def _fetch_sequence(monkeypatch, outcomes):
    calls = []

    def fake_fetch(*args, **kwargs):
        calls.append(1)
        outcome = outcomes[len(calls) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(google_flights, "get_flights_from_filter", fake_fetch)
    return calls


async def test_a_transient_failure_is_retried_and_the_flights_come_back(monkeypatch, no_real_sleep):
    calls = _fetch_sequence(monkeypatch, [OSError("Network is unreachable"), GOOD])
    s = GoogleFlightsSearcher()
    flights = await s.search("CNF", "GIG", DAY)
    assert len(flights) == 1 and len(calls) == 2
    assert no_real_sleep == [1.0]
    assert (s.queries, s.failures) == (1, 0)


async def test_the_third_attempt_can_still_succeed(monkeypatch, no_real_sleep):
    calls = _fetch_sequence(monkeypatch, [OSError("x"), OSError("x"), GOOD])
    s = GoogleFlightsSearcher()
    assert len(await s.search("CNF", "GIG", DAY)) == 1
    assert len(calls) == 3 and no_real_sleep == [1.0, 2.0]
    assert s.failures == 0


async def test_gives_up_after_three_attempts_with_a_single_warning(monkeypatch, caplog):
    calls = _fetch_sequence(monkeypatch, [OSError("x")] * 3)
    s = GoogleFlightsSearcher()
    with caplog.at_level(logging.DEBUG):
        assert await s.search("CNF", "GIG", DAY) == []
    assert len(calls) == 3
    assert (s.queries, s.failures) == (1, 1)
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1


async def test_no_flights_found_is_an_answer_not_a_failure(monkeypatch, caplog):
    calls = _fetch_sequence(monkeypatch, [RuntimeError("No flights found:\n" + "page text " * 500)])
    s = GoogleFlightsSearcher()
    with caplog.at_level(logging.DEBUG):
        assert await s.search("CNF", "FTE", DAY) == []
    assert len(calls) == 1
    assert (s.queries, s.failures) == (1, 0)
    assert all(len(r.getMessage()) < 200 for r in caplog.records)


async def test_reset_counters():
    s = GoogleFlightsSearcher()
    s.queries, s.failures = 9, 4
    s.reset_counters()
    assert (s.queries, s.failures) == (0, 0)
