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
