import json
from datetime import date, timedelta, timezone, datetime

import cache
import cycle
import history
from airlines.google_flights import GoogleFlightsSearcher
from airlines.base import Flight


def _canned(dest="GIG", price=300.0):
    d = date.today() + timedelta(days=40)
    return [
        Flight("CNF", dest, "Azul", d, "12h00", "13h15", price, True, 0, "u"),
        Flight("CNF", dest, "LATAM", d, "07h00", "08h15", price + 96.0, True, 0, "u"),
    ]


def _only_gig(canned, monkeypatch):
    async def fake_search_dates(self, origin, destination, dates, batch_size=7):
        return canned if (origin, destination) == ("CNF", "GIG") else []

    monkeypatch.setattr(GoogleFlightsSearcher, "search_dates", fake_search_dates)


async def _silence_telegram(monkeypatch):
    import telegram_bot

    async def noop(*args, **kwargs):
        return True

    monkeypatch.setattr(telegram_bot, "send_azul_alert", noop)
    monkeypatch.setattr(telegram_bot, "send_price_alert", noop)
    monkeypatch.setattr(telegram_bot, "send_round_trip_alert", noop)
    await cache.init_db()


async def test_cycle_records_this_pass_prices_into_the_history(monkeypatch, tmp_path):
    await _silence_telegram(monkeypatch)
    _only_gig(_canned(price=300.0), monkeypatch)
    monkeypatch.setattr(cycle, "DEALS_PATH", str(tmp_path / "deals.json"))
    await history.init_db()

    await cycle.run_azul_cycle()

    assert any(k.startswith("CNF|GIG|") for k in (await history.stats(days=365)))


async def test_cycle_enriches_the_snapshot_with_previously_recorded_prices(monkeypatch, tmp_path):
    await _silence_telegram(monkeypatch)
    await history.init_db()
    dep = (date.today() + timedelta(days=40)).isoformat()
    for days_ago, price in ((3, 500.0), (2, 400.0)):
        await history.record(
            [{"origem": "CNF", "destino": "GIG", "data": dep, "preco": price}],
            seen_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        )

    _only_gig(_canned(price=300.0), monkeypatch)
    deals_path = tmp_path / "deals.json"
    monkeypatch.setattr(cycle, "DEALS_PATH", str(deals_path))

    await cycle.run_azul_cycle()

    deals = json.load(open(deals_path, encoding="utf-8"))["deals"]
    gig = next(d for d in deals if d["destino"] == "GIG" and d["data"] == dep)
    assert gig["hist_min"] == 400.0
    assert gig["delta_pct"] == -33
    assert gig["menor_hist"] is True
    assert gig["spark"] == [500.0, 400.0]
