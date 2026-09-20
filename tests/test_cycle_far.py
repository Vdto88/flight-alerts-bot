import json
import os
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

import cache
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


async def _seed_history(prices_by_days_ago: dict[int, float]) -> None:
    """Give CNF|GIG|FAR_DAY a series older than today, so enrich_with_history has something
    to compare against on the very first cycle. 700 then 500 → median 600 today, and 500 once
    today's own 300 joins the series — two clearly different verdicts."""
    await history.init_db()
    for days_ago, price in prices_by_days_ago.items():
        await history.record(
            [{"origem": "CNF", "destino": "GIG", "data": FAR_DAY.isoformat(), "preco": price}],
            seen_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        )


def _far_file_records() -> list[dict]:
    stored = json.loads(far_cache.FAR_PATH.read_text(encoding="utf-8"))["deals"]
    return [d for d in stored if d["data"] == FAR_DAY.isoformat()]


async def test_the_far_file_stores_records_that_already_carry_their_history(monkeypatch):
    await cache.init_db()
    await _seed_history({3: 700.0, 2: 500.0})
    _patch(monkeypatch, [])

    await cycle.run_azul_cycle(include_far=True)
    stored = _far_file_records()
    assert len(stored) == 1
    assert stored[0]["hist_med"] == 600.0 and stored[0]["delta_pct"] == -50


async def test_a_carried_record_keeps_the_verdict_of_the_cycle_that_searched_it(monkeypatch):
    # Today's price was recorded by this morning's far cycle, so re-enriching the carried
    # record here would compare its fare against a median that already contains itself.
    await cache.init_db()
    await _seed_history({3: 700.0, 2: 500.0})
    _patch(monkeypatch, [])

    await cycle.run_azul_cycle(include_far=True)
    far_verdict = _far_file_records()[0]["delta_pct"]

    await cycle.run_azul_cycle(include_far=False)
    carried = [d for d in _snapshot() if d["data"] == FAR_DAY.isoformat()]
    assert len(carried) == 1 and carried[0]["visto_em"]
    assert carried[0]["delta_pct"] == far_verdict == -50   # not the -40 of a self-inclusive median


async def test_carried_records_cannot_rescue_an_empty_cycle(monkeypatch):
    await cache.init_db()
    _patch(monkeypatch, [])
    await cycle.run_azul_cycle(include_far=True)       # far file now has records
    os.remove(cycle.DEALS_PATH)

    async def nothing(self, origin, destination, dates, batch_size=7):
        return []

    monkeypatch.setattr(GoogleFlightsSearcher, "search_dates", nothing)
    health = AsyncMock(return_value=True)
    monkeypatch.setattr(telegram_bot, "send_health_alert", health)
    with pytest.raises(cycle.EmptyCycleError):
        await cycle.run_azul_cycle(include_far=False)
    health.assert_awaited_once()
    assert not os.path.exists(cycle.DEALS_PATH)        # no snapshot full of stale fares


async def test_near_cycle_does_not_overwrite_the_far_file(monkeypatch):
    await cache.init_db()
    _patch(monkeypatch, [])
    await cycle.run_azul_cycle(include_far=True)
    before = far_cache.FAR_PATH.read_text(encoding="utf-8")
    await cycle.run_azul_cycle(include_far=False)
    assert far_cache.FAR_PATH.read_text(encoding="utf-8") == before
