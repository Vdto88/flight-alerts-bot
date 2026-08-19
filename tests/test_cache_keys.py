import asyncio
from pathlib import Path
import cache


def test_save_and_read_raw_key(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "DB_PATH", Path(tmp_path) / "cache.db")

    async def scenario():
        await cache.init_db()
        assert await cache.is_key_cached("rt:Europa|x") is False
        await cache.save_key("rt:Europa|x", ttl_hours=24)
        assert await cache.is_key_cached("rt:Europa|x") is True
        assert await cache.is_key_cached("rt:Europa|y") is False

    asyncio.run(scenario())
