from datetime import date, datetime, time, timedelta, timezone

import aiosqlite

import history
from airlines.base import Flight


def _at(days_ago, hour=12):
    day = datetime.now(timezone.utc).date() - timedelta(days=days_ago)
    return datetime.combine(day, time(hour), tzinfo=timezone.utc)


def _deal(destino="GIG", data="2027-01-15", preco=300.0):
    return {"origem": "CNF", "destino": destino, "data": data, "preco": preco}


async def test_stats_reports_when_the_window_low_was_first_seen_and_how_many_days():
    await history.init_db()
    for days_ago, price in ((5, 400.0), (4, 300.0), (3, 350.0), (2, 300.0)):
        await history.record([_deal(preco=price)], seen_at=_at(days_ago))
    entry = (await history.stats())["CNF|GIG|2027-01-15"]
    assert entry["min"] == 300.0 and entry["n"] == 4
    assert entry["since"] == _at(4).date().isoformat()


async def test_stats_window_defaults_to_sixty_days():
    await history.init_db()
    await history.record([_deal(preco=100.0)], seen_at=_at(59))
    await history.record([_deal(preco=900.0)], seen_at=_at(61))
    assert (await history.stats())["CNF|GIG|2027-01-15"]["min"] == 100.0


async def test_route_stats_pairs_each_flight_dates_floor_with_its_typical_price():
    await history.init_db()
    # 2027-01-15 is a Friday (weekday 4); 2027-02-01 is a Monday (weekday 0).
    await history.record([_deal(data="2027-01-15", preco=400.0)], seen_at=_at(3))
    await history.record([_deal(data="2027-01-15", preco=300.0)], seen_at=_at(2))
    await history.record([_deal(data="2027-02-01", preco=500.0)], seen_at=_at(2))
    r = (await history.route_stats())["CNF|GIG"]
    # floors 300 / 500; typical prices 350 / 500 -> median 425
    assert (r["min"], r["med"], r["n_dates"]) == (300.0, 425.0, 2)
    assert r["by_month"] == {"01": 350.0, "02": 500.0}
    assert r["by_dow"] == {"4": 350.0, "0": 500.0}
    assert r["lead_curve"] == [] and r["n_closed"] == 0


async def test_route_median_is_the_typical_price_while_the_floor_stays_the_floor():
    """A date seen at 500, 400 and 300 costs 400 on a typical day; only 'min' is 300."""
    await history.init_db()
    for days_ago, price in ((3, 500.0), (2, 400.0), (1, 300.0)):
        await history.record([_deal(preco=price)], seen_at=_at(days_ago))
    r = (await history.route_stats())["CNF|GIG"]
    assert (r["med"], r["min"]) == (400.0, 300.0)


async def test_route_stats_merges_departed_flights_and_builds_the_lead_curve():
    await history.init_db()
    async with aiosqlite.connect(history.DB_PATH) as db:
        await db.executemany("INSERT INTO closed_dates VALUES (?, ?, ?, ?, ?, ?, ?)", [
            ("CNF", "GIG", "2026-08-01", 0, 600.0, 650.0, 3),
            ("CNF", "GIG", "2026-08-01", 3, 350.0, 380.0, 9),
            ("CNF", "GIG", "2026-08-02", 3, 450.0, 470.0, 9),
        ])
        await db.commit()
    await history.record([_deal(preco=300.0)], seen_at=_at(1))
    r = (await history.route_stats())["CNF|GIG"]
    assert r["n_dates"] == 3 and r["n_closed"] == 2
    assert r["min"] == 300.0                            # per-date floors: 300, 350, 450
    assert r["med"] == 470.0                            # typical prices: 300, 515, 470
    assert r["lead_curve"] == [{"bucket": 0, "med": 650.0, "n": 1},
                               {"bucket": 3, "med": 425.0, "n": 2}]


async def test_route_stats_ignores_a_malformed_key_instead_of_raising():
    await history.init_db()
    await history.record([_deal(preco=300.0)], seen_at=_at(1))
    async with aiosqlite.connect(history.DB_PATH) as db:
        await db.executemany("INSERT INTO price_daily (route, dia, price) VALUES (?, ?, ?)", [
            ("lixo", "2026-09-01", 9.0),
            ("CNF|GIG|nao-e-data", "2026-09-01", 9.0),
        ])
        await db.commit()
    routes = await history.route_stats()
    assert set(routes) == {"CNF|GIG"}
    assert routes["CNF|GIG"]["n_dates"] == 1


async def test_all_series_is_oldest_first_and_capped():
    await history.init_db()
    for i in range(5):
        await history.record([_deal(preco=100.0 + i)], seen_at=_at(4 - i))
    s = (await history.all_series(max_points=3))["CNF|GIG|2027-01-15"]
    assert [p for _d, p in s] == [102.0, 103.0, 104.0]
    assert s[0][0] < s[-1][0]


async def test_all_series_leaves_older_days_in_the_database_instead_of_reading_them():
    """The cap is applied in SQL, so the whole table never has to be materialised."""
    await history.init_db()
    await history.record([_deal(preco=999.0)], seen_at=_at(200))
    await history.record([_deal(preco=100.0)], seen_at=_at(1))
    assert [p for _d, p in (await history.all_series())["CNF|GIG|2027-01-15"]] == [100.0]


def _flight(price):
    return Flight("CNF", "GIG", "Azul", date(2027, 1, 15), "08h00", "09h00", price, True, 0, "u")


def test_context_prefers_the_history_of_the_exact_date():
    stats = {"CNF|GIG|2027-01-15": {"min": 300.0, "med": 400.0, "spark": [400.0, 300.0],
                                    "since": "2026-09-01", "n": 2}}
    ctx = history.context_for(_flight(280.0), stats, {})
    assert ctx == history.HistoryContext(-30, 60, True, "2026-09-01", "data")


def test_context_falls_back_to_the_route_when_the_date_is_new():
    routes = {"CNF|GIG": {"med": 500.0, "min": 320.0, "n_dates": 40}}
    ctx = history.context_for(_flight(400.0), {}, routes)
    assert (ctx.delta_pct, ctx.scope, ctx.is_lowest, ctx.since) == (-20, "rota", False, None)


def test_context_is_none_without_enough_history():
    thin = {"CNF|GIG": {"med": 500.0, "min": 320.0, "n_dates": history.MIN_ROUTE_DATES - 1}}
    one_point = {"CNF|GIG|2027-01-15": {"min": 300.0, "med": 300.0, "spark": [300.0],
                                        "since": "2026-09-01", "n": 1}}
    assert history.context_for(_flight(400.0), one_point, thin) is None
