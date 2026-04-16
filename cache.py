import aiosqlite
from datetime import datetime, timedelta, timezone
from pathlib import Path

from airlines.base import Flight

DB_PATH = Path("data/cache.db")


async def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS seen_flights (
                id          INTEGER PRIMARY KEY,
                cache_key   TEXT UNIQUE NOT NULL,
                detected_at TIMESTAMP NOT NULL,
                expires_at  TIMESTAMP NOT NULL
            )
        """)
        await db.commit()


async def purge_expired() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM seen_flights WHERE expires_at < ?",
            (datetime.now(timezone.utc),)
        )
        await db.commit()


async def is_cached(flight: Flight, ttl_hours: int = 24) -> bool:
    key = flight.cache_key()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM seen_flights WHERE cache_key = ? AND expires_at > ?",
            (key, datetime.now(timezone.utc)),
        ) as cursor:
            return await cursor.fetchone() is not None


async def save_to_cache(flight: Flight, ttl_hours: int = 24) -> None:
    key = flight.cache_key()
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=ttl_hours)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO seen_flights (cache_key, detected_at, expires_at) VALUES (?, ?, ?)",
            (key, now, expires),
        )
        await db.commit()
