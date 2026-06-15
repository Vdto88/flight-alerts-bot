from datetime import date

import cache
import config
import routing
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
    assert topic_id == routing.group_of("GIG", config.GROUPS).topic_id  # Rio topic


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


async def test_run_cycle_passes_group_topic_id(monkeypatch):
    await cache.init_db()
    canned = _canned("GIG")

    async def fake_search_dates(self, origin, destination, dates, batch_size=7):
        return canned if (origin, destination) == ("CNF", "GIG") else []

    monkeypatch.setattr(GoogleFlightsSearcher, "search_dates", fake_search_dates)

    # Route GIG via a group that DOES have a topic configured.
    monkeypatch.setattr(cycle, "GROUPS", [config.Group("Rio", ("GIG",), topic_id=99)])

    sent = []

    async def fake_send(flight, comparison, topic_id=None):
        sent.append(topic_id)
        return True

    monkeypatch.setattr(telegram_bot, "send_azul_alert", fake_send)

    await cycle.run_azul_cycle()

    assert sent == [99]   # the route's topic_id reached the send call


async def test_run_cycle_sends_price_alert_to_region_topic(monkeypatch):
    await cache.init_db()
    d = date(2026, 9, 10)
    canned = [Flight("CNF", "SJK", "GOL", d, "08h00", "09h00", 380.0, True, 0, "u")]

    async def fake_search_dates(self, origin, destination, dates, batch_size=7):
        return canned if (origin, destination) == ("CNF", "SJK") else []

    monkeypatch.setattr(GoogleFlightsSearcher, "search_dates", fake_search_dates)
    monkeypatch.setattr(cycle, "GROUPS", [config.Group("SP", ("SJK",), topic_id=6)])
    monkeypatch.setattr(cycle, "PRICE_WATCHES", [config.PriceWatch("SJK", config.month(2026, 9), 400.0)])

    sent = []

    async def fake_price(flight, max_price, topic_id=None):
        sent.append((flight, max_price, topic_id))
        return True

    monkeypatch.setattr(telegram_bot, "send_price_alert", fake_price)

    await cycle.run_azul_cycle()

    assert len(sent) == 1
    flight, max_price, topic_id = sent[0]
    assert flight.airline == "GOL" and max_price == 400.0 and topic_id == 6


async def test_run_cycle_dedups_price_alert(monkeypatch):
    await cache.init_db()
    d = date(2026, 9, 10)
    canned = [Flight("CNF", "SJK", "GOL", d, "08h00", "09h00", 380.0, True, 0, "u")]

    async def fake_search_dates(self, origin, destination, dates, batch_size=7):
        return canned if (origin, destination) == ("CNF", "SJK") else []

    monkeypatch.setattr(GoogleFlightsSearcher, "search_dates", fake_search_dates)
    monkeypatch.setattr(cycle, "GROUPS", [config.Group("SP", ("SJK",), topic_id=6)])
    monkeypatch.setattr(cycle, "PRICE_WATCHES", [config.PriceWatch("SJK", config.month(2026, 9), 400.0)])

    sent = []

    async def fake_price(flight, max_price, topic_id=None):
        sent.append(flight)
        return True

    monkeypatch.setattr(telegram_bot, "send_price_alert", fake_price)

    await cycle.run_azul_cycle()
    await cycle.run_azul_cycle()
    assert len(sent) == 1   # price namespace dedups the second pass


async def test_run_cycle_azul_and_price_both_fire(monkeypatch):
    await cache.init_db()
    d = date(2026, 9, 10)
    canned = [
        Flight("CNF", "SJK", "Azul", d, "08h00", "09h00", 300.0, True, 0, "u"),
        Flight("CNF", "SJK", "LATAM", d, "07h00", "08h00", 450.0, True, 0, "u"),
    ]

    async def fake_search_dates(self, origin, destination, dates, batch_size=7):
        return canned if (origin, destination) == ("CNF", "SJK") else []

    monkeypatch.setattr(GoogleFlightsSearcher, "search_dates", fake_search_dates)
    monkeypatch.setattr(cycle, "GROUPS", [config.Group("SP", ("SJK",), topic_id=6)])
    monkeypatch.setattr(cycle, "PRICE_WATCHES", [config.PriceWatch("SJK", config.month(2026, 9), 400.0)])

    azul_sent, price_sent = [], []

    async def fake_azul(flight, comparison, topic_id=None):
        azul_sent.append(flight)
        return True

    async def fake_price(flight, max_price, topic_id=None):
        price_sent.append(flight)
        return True

    monkeypatch.setattr(telegram_bot, "send_azul_alert", fake_azul)
    monkeypatch.setattr(telegram_bot, "send_price_alert", fake_price)

    await cycle.run_azul_cycle()
    assert len(azul_sent) == 1   # Azul is cheapest (300 < 450)
    assert len(price_sent) == 1  # 300 <= 400 limit — independent namespaces
