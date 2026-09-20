"""Far-band panel records carried between far cycles.

The far band (beyond WINDOW_MAX_DAYS) is searched once a day, but the panel snapshot is
rebuilt on every cycle from what that cycle searched. Without this file the far dates would
show up in the morning and vanish in the afternoon. Lives in data/, which actions/cache
persists; losing it only hides far dates until the next far cycle. Never raises.
"""
import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

FAR_PATH = Path("data/far_deals.json")
MAX_AGE_HOURS = 36      # one missed far cycle is tolerated; two are not
_STAMP = "%Y-%m-%dT%H:%M:%SZ"


def _key(deal: dict) -> str:
    return f"{deal['origem']}|{deal['destino']}|{deal['data']}"


def is_far(deal: dict, today: date, near_max_days: int) -> bool:
    if deal.get("tipo") == "roundtrip":
        return False
    return date.fromisoformat(deal["data"]) > today + timedelta(days=near_max_days)


def save(deals: list[dict], today: date, near_max_days: int, now: datetime | None = None) -> int:
    """Store the far-band subset of a far cycle's deals. Returns how many were written."""
    far = [d for d in deals if is_far(d, today, near_max_days)]
    stamp = (now or datetime.now(timezone.utc)).strftime(_STAMP)
    try:
        FAR_PATH.parent.mkdir(parents=True, exist_ok=True)
        FAR_PATH.write_text(json.dumps({"visto_em": stamp, "deals": far}, ensure_ascii=False),
                            encoding="utf-8")
    except OSError as e:
        logger.error(f"datas distantes não gravadas: {e}")
        return 0
    return len(far)


def load_carried(existing_deals: list[dict], today: date, near_max_days: int,
                 now: datetime | None = None) -> list[dict]:
    """Far-band records from the last far cycle that this cycle did not search itself, each
    stamped with `visto_em`. Empty when the file is missing, malformed or too old."""
    try:
        stored = json.loads(FAR_PATH.read_text(encoding="utf-8"))
        seen_at = datetime.strptime(stored["visto_em"], _STAMP).replace(tzinfo=timezone.utc)
        deals = stored["deals"]
        if not isinstance(deals, list):
            raise ValueError("deals is not a list")
    except FileNotFoundError:
        return []
    except (OSError, ValueError, KeyError, TypeError) as e:
        logger.warning(f"datas distantes ignoradas, arquivo ilegível: {e!r}")
        return []

    age = (now or datetime.now(timezone.utc)) - seen_at
    if age > timedelta(hours=MAX_AGE_HOURS):
        logger.warning(f"datas distantes ignoradas: vistas há {age}, limite {MAX_AGE_HOURS} h")
        return []

    # A round-trip record mirrors its ida leg's origem|destino|data, so it would mask the
    # one-way record for the same far date. Only a searched one-way counts as "already
    # covered". Malformed records are skipped rather than raised on: this module never raises.
    have = set()
    for d in existing_deals:
        try:
            if d.get("tipo") != "roundtrip":
                have.add(_key(d))
        except (KeyError, TypeError, AttributeError):
            continue
    carried = []
    for d in deals:
        try:
            if is_far(d, today, near_max_days) and _key(d) not in have:
                carried.append({**d, "visto_em": stored["visto_em"]})
        except (KeyError, ValueError, TypeError):
            continue
    return carried
