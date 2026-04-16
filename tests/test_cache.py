import pytest
from datetime import date, timezone
from airlines.base import Flight
import cache


def _make_flight(price: float = 289.90, dep_date: date = date(2026, 5, 15)) -> Flight:
    return Flight(
        origin="CNF",
        destination="GRU",
        airline="GOL",
        departure_date=dep_date,
        departure_time="07h40",
        arrival_time="09h10",
        price=price,
        is_direct=True,
        stops=0,
        booking_url="https://example.com",
    )


async def test_is_cached_returns_false_for_new_flight():
    await cache.init_db()
    flight = _make_flight()
    assert await cache.is_cached(flight) is False


async def test_save_then_is_cached_returns_true():
    await cache.init_db()
    flight = _make_flight()
    await cache.save_to_cache(flight)
    assert await cache.is_cached(flight) is True


async def test_same_price_floor_hits_cache():
    # 289.90 and 289.50 share price_floor=280 → same cache key
    await cache.init_db()
    flight1 = _make_flight(price=289.90)
    flight2 = _make_flight(price=289.50)
    await cache.save_to_cache(flight1)
    assert await cache.is_cached(flight2) is True


async def test_different_price_floor_misses_cache():
    # 289.90 (floor=280) vs 279.90 (floor=270) → different keys
    await cache.init_db()
    flight1 = _make_flight(price=289.90)
    flight2 = _make_flight(price=279.90)
    await cache.save_to_cache(flight1)
    assert await cache.is_cached(flight2) is False


async def test_purge_removes_expired(monkeypatch):
    import cache
    from datetime import datetime, timedelta

    await cache.init_db()
    flight = _make_flight()
    await cache.save_to_cache(flight, ttl_hours=1)

    # Fake that entry expired by backdating expires_at
    import aiosqlite
    async with aiosqlite.connect(cache.DB_PATH) as db:
        past = datetime.now(timezone.utc) - timedelta(hours=2)
        await db.execute("UPDATE seen_flights SET expires_at = ?", (past,))
        await db.commit()

    await cache.purge_expired()
    assert await cache.is_cached(flight) is False
