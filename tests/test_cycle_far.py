import json
from datetime import date, timedelta

import cache
import config
import cycle
import far_cache
import history
import telegram_bot
from airlines.base import Flight
from airlines.google_flights import GoogleFlightsSearcher

FAR_DAY = date.today() + timedelta(days=150)
NEAR_DAY = date.today() + timedelta(days=40)


def _patch(monkeypatch, sent):
    async def fake_search_dates(self, origin, destination, dates, batch_size=7):
        if (origin, destination) != ("CNF", "GIG"):
            return []
        return [Flight("CNF", "GIG", "Azul", d, "07h00", "08h00", 300.0, True, 0, "u")
                for d in (NEAR_DAY, FAR_DAY) if d in dates] + \
               [Flight("CNF", "GIG", "LATAM", d, "09h00", "10h00", 400.0, True, 0, "u")
                for d in (NEAR_DAY, FAR_DAY) if d in dates]

    async def fake_azul(flight, comparison, topic_id=None, context=None):
        sent.append(flight.departure_date)
        return True

    async def ok(*args, **kwargs):
        return True

    monkeypatch.setattr(GoogleFlightsSearcher, "search_dates", fake_search_dates)
    monkeypatch.setattr(telegram_bot, "send_azul_alert", fake_azul)
    monkeypatch.setattr(telegram_bot, "send_price_alert", ok)
    monkeypatch.setattr(telegram_bot, "send_round_trip_alert", ok)


def _snapshot():
    return json.load(open(cycle.DEALS_PATH, encoding="utf-8"))["deals"]


async def test_far_cycle_saves_and_near_cycle_carries_without_alerting_again(monkeypatch):
    await cache.init_db()
    sent: list = []
    _patch(monkeypatch, sent)

    await cycle.run_azul_cycle(include_far=True)
    assert FAR_DAY in sent
    far_now = [d for d in _snapshot() if d["data"] == FAR_DAY.isoformat()]
    assert len(far_now) == 1 and "visto_em" not in far_now[0]
    assert far_cache.FAR_PATH.exists()

    sent.clear()
    await cycle.run_azul_cycle(include_far=False)
    assert FAR_DAY not in sent                                   # carried, never re-alerted
    carried = [d for d in _snapshot() if d["data"] == FAR_DAY.isoformat()]
    assert len(carried) == 1 and carried[0]["visto_em"]
    assert carried[0]["azul_cheapest"] is True                   # flag travels with the record


async def test_carried_records_are_not_recorded_into_history_again(monkeypatch):
    await cache.init_db()
    _patch(monkeypatch, [])
    await cycle.run_azul_cycle(include_far=True)

    recorded: list = []
    real_record = history.record

    async def spy(deals, seen_at=None):
        recorded.extend(deals)
        return await real_record(deals, seen_at)

    monkeypatch.setattr(history, "record", spy)
    await cycle.run_azul_cycle(include_far=False)
    assert all("visto_em" not in d for d in recorded)
    assert FAR_DAY.isoformat() not in {d["data"] for d in recorded}


async def test_near_cycle_does_not_overwrite_the_far_file(monkeypatch):
    await cache.init_db()
    _patch(monkeypatch, [])
    await cycle.run_azul_cycle(include_far=True)
    before = far_cache.FAR_PATH.read_text(encoding="utf-8")
    await cycle.run_azul_cycle(include_far=False)
    assert far_cache.FAR_PATH.read_text(encoding="utf-8") == before
