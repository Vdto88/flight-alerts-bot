"""What the promotions cycle remembers between hourly runs, in one JSON file.

The same file is the dedup memory (seen guids) and the source of the panel section (accepted
promotions of the last two weeks). It lives in promo_data/, persisted by actions/cache under
its own key: only the promotions workflow writes it, the main workflow only reads it. Losing it
costs a quiet re-seed, so load() and save() never raise.
"""
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from promos.classify import Classification
from promos.feeds import FeedItem

logger = logging.getLogger(__name__)

STATE_PATH = Path("promo_data/promos_state.json")
PAYLOAD_PATH = Path("promo_data/promos.json")
SEEN_DAYS = 30        # feeds hold a few days of posts; a month of guids is ample
PROMO_DAYS = 14       # how far back the panel section goes
MAX_ATTEMPTS = 3      # failed sends before an item is given up on
HEALTH_AFTER = 6      # consecutive failed cycles before the owner is told a feed is down
_STAMP = "%Y-%m-%dT%H:%M:%SZ"


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime(_STAMP)


def _parse(stamp: str) -> datetime:
    return datetime.strptime(stamp, _STAMP).replace(tzinfo=timezone.utc)


@dataclass
class PromoState:
    seen: dict[str, str] = field(default_factory=dict)          # guid -> when it was settled
    promos: list[dict] = field(default_factory=list)            # payload records plus "guid"
    attempts: dict[str, int] = field(default_factory=dict)      # guid -> failed sends
    feed_failures: dict[str, int] = field(default_factory=dict) # source -> consecutive failures
    health_alerted: list[str] = field(default_factory=list)     # sources already reported down
    seeding: bool = False                                       # no usable state: do not flood

    def is_seen(self, guid: str) -> bool:
        return guid in self.seen

    def mark_seen(self, guid: str, now: datetime) -> None:
        self.seen[guid] = _iso(now)
        self.attempts.pop(guid, None)

    def add_promo(self, item: FeedItem, c: Classification) -> None:
        if any(p["guid"] == item.guid for p in self.promos):
            return
        self.promos.append({
            "guid": item.guid,
            "tipo": "passagem" if c.kind == "fare" else "milhas",
            "titulo": item.title,
            "resumo": item.summary,
            "link": item.link,
            "fonte": item.source,
            "publicado_em": _iso(item.published_at),
            "destinos": list(c.destinations),
            "programas": list(c.programs),
            "origem_bh": c.from_bh,
            "origem_nao_informada": c.origin_unknown,
        })

    def record_attempt(self, guid: str) -> int:
        self.attempts[guid] = self.attempts.get(guid, 0) + 1
        return self.attempts[guid]

    def record_feed_result(self, source: str, ok: bool) -> bool:
        """True exactly once per outage: when the feed has just failed HEALTH_AFTER cycles in a row."""
        if ok:
            self.feed_failures.pop(source, None)
            if source in self.health_alerted:
                self.health_alerted.remove(source)
            return False
        self.feed_failures[source] = self.feed_failures.get(source, 0) + 1
        if self.feed_failures[source] >= HEALTH_AFTER and source not in self.health_alerted:
            self.health_alerted.append(source)
            return True
        return False

    def prune(self, now: datetime) -> None:
        seen_floor = _iso(now - timedelta(days=SEEN_DAYS))
        promo_floor = _iso(now - timedelta(days=PROMO_DAYS))
        self.seen = {g: s for g, s in self.seen.items() if s >= seen_floor}   # ISO sorts as text
        self.promos = [p for p in self.promos if p["publicado_em"] >= promo_floor]

    def payload(self, now: datetime) -> dict:
        newest_first = sorted(self.promos, key=lambda p: p["publicado_em"], reverse=True)
        return {"gerado_em": _iso(now),
                "promos": [{k: v for k, v in p.items() if k != "guid"} for p in newest_first]}


def load(path: Path = STATE_PATH) -> PromoState:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        state = PromoState(
            seen=dict(raw["seen"]), promos=list(raw["promos"]), attempts=dict(raw.get("attempts", {})),
            feed_failures=dict(raw.get("feed_failures", {})),
            health_alerted=list(raw.get("health_alerted", [])),
        )
        for stamp in state.seen.values():
            _parse(stamp)
    except FileNotFoundError:
        return PromoState(seeding=True)
    except (OSError, ValueError, KeyError, TypeError) as e:
        logger.warning(f"estado das promoções ilegível, recomeçando: {e!r}")
        return PromoState(seeding=True)
    state.seeding = not state.seen
    return state


def save(state: PromoState, now: datetime, state_path: Path = STATE_PATH,
         payload_path: Path = PAYLOAD_PATH) -> None:
    state.prune(now)
    body = {k: v for k, v in asdict(state).items() if k != "seeding"}
    try:
        for path, content in ((Path(state_path), body), (Path(payload_path), state.payload(now))):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
    except OSError as e:
        logger.error(f"estado das promoções não gravado: {e}")
