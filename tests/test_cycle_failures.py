from datetime import date, timedelta
from unittest.mock import AsyncMock

import cache
import cycle
import telegram_bot
from airlines.base import Flight
from airlines.google_flights import GoogleFlightsSearcher


def _patch(monkeypatch, queries, failures):
    async def fake_search_dates(self, origin, destination, dates, batch_size=7):
        if (origin, destination) == ("CNF", "GIG"):
            self.queries, self.failures = queries, failures     # as if the whole cycle ran here
            d = date.today() + timedelta(days=40)
            return [Flight("CNF", "GIG", "LATAM", d, "07h00", "08h00", 300.0, True, 0, "u")]
        return []

    async def ok(*args, **kwargs):
        return True

    monkeypatch.setattr(GoogleFlightsSearcher, "search_dates", fake_search_dates)
    for name in ("send_azul_alert", "send_price_alert", "send_round_trip_alert"):
        monkeypatch.setattr(telegram_bot, name, ok)
    health = AsyncMock(return_value=True)
    monkeypatch.setattr(telegram_bot, "send_health_alert", health)
    return health


async def test_health_alert_when_more_than_half_of_the_queries_fail(monkeypatch, caplog):
    await cache.init_db()
    health = _patch(monkeypatch, queries=100, failures=51)
    with caplog.at_level("INFO"):
        await cycle.run_azul_cycle()
    health.assert_awaited_once()
    assert "consultas: 100 | falhas: 51" in caplog.text


async def test_no_health_alert_at_or_below_half(monkeypatch):
    await cache.init_db()
    health = _patch(monkeypatch, queries=100, failures=50)
    await cycle.run_azul_cycle()
    health.assert_not_awaited()


async def test_counters_start_from_zero_each_cycle(monkeypatch):
    await cache.init_db()
    cycle._searcher.queries, cycle._searcher.failures = 500, 500
    cycle._searcher.no_flights = 500
    health = _patch(monkeypatch, queries=10, failures=0)
    await cycle.run_azul_cycle()
    health.assert_not_awaited()
    assert cycle._searcher.no_flights == 0


async def test_summary_reports_fareless_dates_and_how_long_the_cycle_took(monkeypatch, caplog):
    # "sem voos" is the tell-tale for the _NO_FLIGHTS match breaking upstream (it would drop
    # to zero); "duração" is how a far cycle drifting toward the job timeout becomes visible.
    await cache.init_db()
    _patch(monkeypatch, queries=10, failures=0)
    with caplog.at_level("INFO"):
        await cycle.run_azul_cycle()
    assert "sem voos:" in caplog.text
    assert "duração:" in caplog.text
