import calendar
import os
from dataclasses import dataclass
from datetime import date

from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID: str = os.environ.get("TELEGRAM_CHANNEL_ID", "")

# --- Azul-cheapest alert ---
AZUL_HUB: str = "CNF"


@dataclass(frozen=True)
class SearchWindow:
    start: date          # inclusive
    end: date            # inclusive


def month(year: int, m: int) -> "SearchWindow":
    """Whole calendar month as a window. month(2027, 2) -> Feb 1..Feb 28/29."""
    last = calendar.monthrange(year, m)[1]
    return SearchWindow(date(year, m, 1), date(year, m, last))


@dataclass(frozen=True)
class Group:
    name: str                                  # display name; also the topic name
    airports: tuple[str, ...]                  # IATA codes
    windows: tuple[SearchWindow, ...] = ()     # extra ranges; empty = rolling-only
    topic_id: int | None = None                # Telegram forum topic id; None = General


@dataclass(frozen=True)
class PriceWatch:
    airport: str          # IATA; must be a member of some Group (for routing + topic)
    window: SearchWindow  # e.g. month(2026, 9)
    max_price: float      # BRL; alert when the cheapest fare (any airline) <= this


GROUPS: list[Group] = [
    Group("Rio de Janeiro", ("GIG", "SDU"), topic_id=4),
    Group("São Paulo",      ("CGH", "SJK"), topic_id=6),
    Group("São Luís",       ("SLZ",), topic_id=8),
    Group("Sul",            ("FLN", "NVT", "POA"), topic_id=10),   # tópico "FLORIANÓPOLIS" (Floripa + Navegantes + Porto Alegre)
    Group("Foz do Iguaçu",  ("IGU",), (month(2026, 10),), topic_id=2),
    Group("Patagônia",      ("FTE", "PNT", "PMC", "PUQ", "BRC", "SCL"), (month(2027, 2), month(2027, 3)), topic_id=12),
    # --- Europa ---
    Group("Portugal",       ("LIS", "OPO"), topic_id=14),
    Group("Espanha",        ("MAD", "BCN"), topic_id=16),
    Group("Itália",         ("FCO", "MXP"), topic_id=18),
    Group("França",         ("CDG", "ORY"), topic_id=20),
]
PRICE_WATCHES: list[PriceWatch] = [
    PriceWatch("SJK", month(2026, 9), 400.0),   # São José dos Campos, Sep/2026, <= R$400
]

# Rolling window of departure dates to check, in days from today.
WINDOW_MIN_DAYS: int = 30
WINDOW_MAX_DAYS: int = 120

BATCH_SIZE: int = 7          # concurrent Google Flights queries per batch
CACHE_TTL_HOURS: int = 24    # dedup window

# --- Miles (dormant; consumed only by scripts/harvest_cookies.py) ---
MILES_ROUTES = [
    {"from": "CNF", "to": "IGU", "miles_threshold": 15000, "program": "SMILES"},
    {"from": "IGU", "to": "CNF", "miles_threshold": 15000, "program": "SMILES"},
    {"from": "CNF", "to": "IGU", "miles_threshold": 20000, "program": "AZUL_MILES"},
    {"from": "IGU", "to": "CNF", "miles_threshold": 20000, "program": "AZUL_MILES"},
]
MILES_DAYS_AHEAD: int = 30
