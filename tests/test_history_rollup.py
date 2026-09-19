from datetime import date

import aiosqlite
import pytest

import history


async def _seed(rows):
    await history.init_db()
    async with aiosqlite.connect(history.DB_PATH) as db:
        await db.executemany("INSERT INTO price_daily (route, dia, price) VALUES (?, ?, ?)", rows)
        await db.commit()


async def _all(sql):
    async with aiosqlite.connect(history.DB_PATH) as db:
        async with db.execute(sql) as cur:
            return await cur.fetchall()


@pytest.mark.parametrize("days, bucket", [
    (0, 0), (7, 0), (8, 1), (14, 1), (15, 2), (30, 2), (31, 3), (60, 3),
    (61, 4), (90, 4), (91, 5), (120, 5), (121, 6), (180, 6), (181, 6), (400, 6),
])
def test_lead_bucket_boundaries(days, bucket):
    assert history.lead_bucket(days) == bucket


async def test_rollup_summarises_a_departed_flight_per_bucket_and_drops_its_detail():
    await _seed([
        ("CNF|GIG|2026-09-10", "2026-09-08", 300.0),   # lead 2  -> bucket 0
        ("CNF|GIG|2026-09-10", "2026-09-05", 280.0),   # lead 5  -> bucket 0
        ("CNF|GIG|2026-09-10", "2026-08-20", 410.0),   # lead 21 -> bucket 2
    ])
    closed = await history.rollup_closed(today=date(2026, 9, 11))

    assert closed == 1
    assert await _all("SELECT origem, destino, data_voo, lead_bucket, min_price, n_obs "
                      "FROM closed_dates ORDER BY lead_bucket") == [
        ("CNF", "GIG", "2026-09-10", 0, 280.0, 2),
        ("CNF", "GIG", "2026-09-10", 2, 410.0, 1),
    ]
    assert await _all("SELECT * FROM price_daily") == []


async def test_rollup_leaves_flights_departing_today_or_later_alone():
    await _seed([("CNF|GIG|2026-09-11", "2026-09-01", 300.0),
                 ("CNF|GIG|2026-12-01", "2026-09-01", 500.0)])
    assert await history.rollup_closed(today=date(2026, 9, 11)) == 0
    assert len(await _all("SELECT * FROM price_daily")) == 2


async def test_rollup_is_safe_to_run_twice():
    await _seed([("CNF|GIG|2026-09-10", "2026-09-08", 300.0)])
    await history.rollup_closed(today=date(2026, 9, 11))
    await history.rollup_closed(today=date(2026, 9, 11))
    assert len(await _all("SELECT * FROM closed_dates")) == 1
