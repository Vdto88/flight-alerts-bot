from datetime import date

import cache
import telegram_bot
import cycle
from airlines.base import Flight
from airlines.google_flights import GoogleFlightsSearcher


def _canned(dest="GIG"):
    d = date(2026, 7, 15)
    return [
        Flight("CNF", dest, "Azul", d, "12h00", "13h15", 300.0, True, 0, "u"),
        Flight("CNF", dest, "LATAM", d, "07h00", "08h15", 396.0, True, 0, "u"),
    ]


async def test_run_cycle_sends_alert_when_azul_cheapest(monkeypatch):
    await cache.init_db()
    canned = _canned("GIG")

    async def fake_search_dates(self, origin, destination, dates, batch_size=7):
        return canned if (origin, destination) == ("CNF", "GIG") else []

    monkeypatch.setattr(GoogleFlightsSearcher, "search_dates", fake_search_dates)

    sent = []

    async def fake_send(flight, comparison, topic_id=None):
        sent.append((flight, comparison, topic_id))
        return True

    monkeypatch.setattr(telegram_bot, "send_azul_alert", fake_send)

    await cycle.run_azul_cycle()

    assert len(sent) == 1
    flight, comp, topic_id = sent[0]
    assert "azul" in flight.airline.lower()
    assert comp.competitor == "LATAM"
    assert topic_id is None   # Rio group has no topic configured


async def test_run_cycle_dedups_within_ttl(monkeypatch):
    await cache.init_db()
    canned = _canned("GIG")

    async def fake_search_dates(self, origin, destination, dates, batch_size=7):
        return canned if (origin, destination) == ("CNF", "GIG") else []

    monkeypatch.setattr(GoogleFlightsSearcher, "search_dates", fake_search_dates)
    sent = []

    async def fake_send(flight, comparison, topic_id=None):
        sent.append(flight)
        return True

    monkeypatch.setattr(telegram_bot, "send_azul_alert", fake_send)

    await cycle.run_azul_cycle()
    await cycle.run_azul_cycle()   # same flight, must be deduped

    assert len(sent) == 1


async def test_run_cycle_retries_when_send_fails(monkeypatch):
    await cache.init_db()
    canned = _canned("GIG")

    async def fake_search_dates(self, origin, destination, dates, batch_size=7):
        return canned if (origin, destination) == ("CNF", "GIG") else []

    monkeypatch.setattr(GoogleFlightsSearcher, "search_dates", fake_search_dates)
    attempts = []

    async def failing_send(flight, comparison, topic_id=None):
        attempts.append(flight)
        return False   # failed send -> must NOT be cached

    monkeypatch.setattr(telegram_bot, "send_azul_alert", failing_send)

    await cycle.run_azul_cycle()
    await cycle.run_azul_cycle()   # failed before -> retried, not deduped

    assert len(attempts) == 2
