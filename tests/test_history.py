from datetime import datetime, time, timedelta, timezone

import aiosqlite

import history


def _deal(origem="CNF", destino="SJK", data="2026-09-10", preco=300.0) -> dict:
    return {"origem": origem, "destino": destino, "data": data, "preco": preco}


def _at(days_ago: int, hour: int = 12) -> datetime:
    """A fixed UTC hour on a past day, so day-bucketing assertions never straddle midnight."""
    day = datetime.now(timezone.utc).date() - timedelta(days=days_ago)
    return datetime.combine(day, time(hour), tzinfo=timezone.utc)


async def test_stats_is_empty_before_any_record():
    await history.init_db()
    assert await history.stats() == {}


async def test_record_then_stats_returns_min_and_median():
    await history.init_db()
    await history.record([_deal(preco=400.0)], seen_at=_at(3))
    await history.record([_deal(preco=300.0)], seen_at=_at(2))
    await history.record([_deal(preco=500.0)], seen_at=_at(1))

    entry = (await history.stats())["CNF|SJK|2026-09-10"]
    assert entry["min"] == 300.0
    assert entry["med"] == 400.0
    assert entry["spark"] == [400.0, 300.0, 500.0]


async def test_spark_keeps_one_point_per_day_using_the_daily_minimum():
    await history.init_db()
    await history.record([_deal(preco=450.0)], seen_at=_at(2, hour=8))
    await history.record([_deal(preco=380.0)], seen_at=_at(2, hour=20))
    await history.record([_deal(preco=600.0)], seen_at=_at(1))

    entry = (await history.stats())["CNF|SJK|2026-09-10"]
    assert entry["spark"] == [380.0, 600.0]
    assert entry["min"] == 380.0


async def test_spark_is_capped_at_14_points_keeping_the_most_recent():
    await history.init_db()
    for i in range(20):
        await history.record([_deal(preco=100.0 + i)], seen_at=_at(19 - i))
    entry = (await history.stats(days=25))["CNF|SJK|2026-09-10"]
    assert len(entry["spark"]) == 14
    assert entry["spark"][0] == 106.0
    assert entry["spark"][-1] == 119.0


async def test_stats_ignores_observations_older_than_the_window():
    await history.init_db()
    await history.record([_deal(preco=100.0)], seen_at=_at(40))
    await history.record([_deal(preco=500.0)], seen_at=_at(2))
    entry = (await history.stats(days=30))["CNF|SJK|2026-09-10"]
    assert entry["min"] == 500.0


async def test_stats_separates_routes_and_departure_dates():
    await history.init_db()
    await history.record([
        _deal(destino="SJK", preco=300.0),
        _deal(destino="POA", preco=800.0),
        _deal(destino="SJK", data="2026-09-11", preco=900.0),
    ], seen_at=_at(1))
    s = await history.stats()
    assert s["CNF|SJK|2026-09-10"]["min"] == 300.0
    assert s["CNF|POA|2026-09-10"]["min"] == 800.0
    assert s["CNF|SJK|2026-09-11"]["min"] == 900.0


async def test_record_skips_deals_without_a_usable_price():
    await history.init_db()
    await history.record([_deal(preco=0.0), {"origem": "CNF", "destino": "SJK", "data": "2026-09-10"}])
    assert await history.stats() == {}


async def test_record_skips_round_trips_because_their_price_is_a_two_leg_total():
    await history.init_db()
    assert await history.record([dict(_deal(preco=2900.0), tipo="roundtrip")]) == 0
    assert await history.stats() == {}


async def test_record_returns_the_number_of_rows_written():
    await history.init_db()
    assert await history.record([_deal(), _deal(destino="POA"), _deal(preco=0.0)]) == 2


async def _rows(sql):
    async with aiosqlite.connect(history.DB_PATH) as db:
        async with db.execute(sql) as cur:
            return await cur.fetchall()


async def test_three_cycles_on_one_day_collapse_into_one_row_holding_the_minimum():
    await history.init_db()
    for hour, price in ((8, 450.0), (14, 380.0), (20, 410.0)):
        await history.record([_deal(preco=price)], seen_at=_at(2, hour=hour))
    assert await _rows("SELECT route, price FROM price_daily") == [("CNF|SJK|2026-09-10", 380.0)]


async def test_init_db_adds_med_price_to_an_older_closed_dates_table():
    async with aiosqlite.connect(history.DB_PATH) as db:
        await db.execute(
            "CREATE TABLE closed_dates (origem TEXT NOT NULL, destino TEXT NOT NULL, "
            "data_voo TEXT NOT NULL, lead_bucket INTEGER NOT NULL, min_price REAL NOT NULL, "
            "n_obs INTEGER NOT NULL, PRIMARY KEY (origem, destino, data_voo, lead_bucket))")
        await db.execute("INSERT INTO closed_dates VALUES ('CNF', 'SJK', '2026-08-01', 0, 420.0, 3)")
        await db.commit()

    await history.init_db()

    assert await _rows("SELECT min_price, med_price FROM closed_dates") == [(420.0, 420.0)]


async def test_init_db_migrates_the_old_per_cycle_table_once():
    async with aiosqlite.connect(history.DB_PATH) as db:
        await db.execute(
            "CREATE TABLE price_history (id INTEGER PRIMARY KEY, route TEXT NOT NULL, "
            "price REAL NOT NULL, seen_at TEXT NOT NULL)")
        await db.executemany(
            "INSERT INTO price_history (route, price, seen_at) VALUES (?, ?, ?)",
            [("CNF|SJK|2026-09-10", 450.0, "2026-09-01T08:00:00+00:00"),
             ("CNF|SJK|2026-09-10", 380.0, "2026-09-01T20:00:00+00:00"),
             ("CNF|SJK|2026-09-10", 500.0, "2026-09-02T08:00:00+00:00")])
        await db.commit()

    await history.init_db()
    await history.init_db()   # second run must be a no-op

    assert await _rows("SELECT dia, price FROM price_daily ORDER BY dia") == [
        ("2026-09-01", 380.0), ("2026-09-02", 500.0)]
    assert await _rows("SELECT name FROM sqlite_master WHERE name = 'price_history'") == []
