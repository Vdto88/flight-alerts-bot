"""Print every item of the live promotion feeds with the verdict the rules give it.

Read-only: sends nothing, writes nothing. Run before activating or after touching the word
lists in config.py:  python scripts/promo_verdicts.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
from promos import feeds  # noqa: E402
from promos.classify import classify  # noqa: E402


async def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    items, ok = await feeds.fetch_all(config.PROMO_FEEDS)
    for source, good in ok.items():
        print(f"# {source}: {'ok' if good else 'FALHOU'}")
    for item in sorted(items, key=lambda i: i.published_at, reverse=True):
        c, reason = classify(item)
        mark = "  --  " if c is None else ("MILHAS" if c.kind == "miles" else "PASSAG")
        print(f"{mark} | {reason:<38} | {item.source[:12]:<12} | {item.title}")


if __name__ == "__main__":
    asyncio.run(main())
