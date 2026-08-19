import asyncio
from datetime import date
import cycle, config
from airlines.base import Flight


def _leg(o, d, dt, price, airline="AZUL"):
    return Flight(origin=o, destination=d, airline=airline, departure_date=dt,
                  departure_time="10h00", arrival_time="20h00", price=price,
                  is_direct=False, stops=1, booking_url=f"http://{o}{d}{dt}")


WATCH = config.RoundTripWatch(
    name="Europa", airports=("CDG",),
    depart_window=config.SearchWindow(date(2027, 3, 1), date(2027, 3, 31)),
    stay_min=13, stay_max=15, max_total=3000.0, topic_id=None,
)


def test_process_round_trips_sends_and_fills_panel(monkeypatch):
    sent_msgs = []
    saved_keys = []

    async def fake_send(rt, topic_id=None):
        sent_msgs.append(rt); return True

    async def fake_is_cached(key):
        return key in saved_keys

    async def fake_save(key, ttl_hours=24):
        saved_keys.append(key)

    monkeypatch.setattr(cycle.telegram_bot, "send_round_trip_alert", fake_send)
    monkeypatch.setattr(cycle.cache, "is_key_cached", fake_is_cached)
    monkeypatch.setattr(cycle.cache, "save_key", fake_save)

    rt_ida = {"Europa": [_leg("CNF", "CDG", date(2027, 3, 1), 1500.0)]}
    rt_volta = {"Europa": [_leg("CDG", "CNF", date(2027, 3, 15), 1400.0)]}
    all_deals = []

    async def run():
        return await cycle.process_round_trips(rt_ida, rt_volta, [WATCH], all_deals, 24)

    count = asyncio.run(run())
    assert count == 1
    assert len(sent_msgs) == 1 and sent_msgs[0].total == 2900.0
    assert len(all_deals) == 1 and all_deals[0]["tipo"] == "roundtrip"

    # second run: same combo already cached -> no new send, panel still filled
    all_deals.clear()
    count2 = asyncio.run(run())
    assert count2 == 0
    assert len(all_deals) == 1  # panel always reflects current qualifying combos
