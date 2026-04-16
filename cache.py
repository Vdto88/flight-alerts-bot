import aiosqlite
from datetime import datetime, timedelta, timezone
from pathlib import Path

from airlines.base import Flight

DB_PATH = Path("data/cache.db")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _expires_iso(ttl_hours: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=ttl_hours)).isoformat()


async def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS seen_flights (
                id          INTEGER PRIMARY KEY,
                cache_key   TEXT UNIQUE NOT NULL,
                detected_at TEXT NOT NULL,
                expires_at  TEXT NOT NULL
            )
        """)
        await db.commit()


async def purge_expired() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM seen_flights WHERE expires_at < ?",
            (_now_iso(),)
        )
        await db.commit()


async def is_cached(flight: Flight) -> bool:
    key = flight.cache_key()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM seen_flights WHERE cache_key = ? AND expires_at > ?",
            (key, _now_iso()),
        ) as cursor:
            return await cursor.fetchone() is not None


async def save_to_cache(flight: Flight, ttl_hours: int = 24) -> None:
    key = flight.cache_key()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO seen_flights (cache_key, detected_at, expires_at) VALUES (?, ?, ?)",
            (key, _now_iso(), _expires_iso(ttl_hours)),
        )
        await db.commit()
