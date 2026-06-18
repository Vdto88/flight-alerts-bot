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
    airport: str                 # IATA; must be a member of some Group (for routing + topic)
    window: SearchWindow | None  # month to watch; None = standing (rolling window only)
    max_price: float             # BRL; alert when the cheapest fare (any airline) <= this


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
    PriceWatch("SLZ", None, 600.0),             # São Luís, standing (rolling window), <= R$600
    PriceWatch("POA", None, 400.0),             # Porto Alegre, standing (rolling window), <= R$400
    PriceWatch("IGU", None, 500.0),             # Foz do Iguaçu, standing (rolling + grupo Out/2026), <= R$500
    # Patagônia (saindo de CNF): standing <= R$1000, qualquer cia.
    # Cobre as datas já buscadas (rolling + janela do grupo Fev+Mar/2027). Zero query extra.
    PriceWatch("FTE", None, 1000.0),            # El Calafate
    PriceWatch("PNT", None, 1000.0),            # Puerto Natales
    PriceWatch("PMC", None, 1000.0),            # Puerto Montt
    PriceWatch("PUQ", None, 1000.0),            # Punta Arenas
    PriceWatch("BRC", None, 1000.0),            # Bariloche
    PriceWatch("SCL", None, 1000.0),            # Santiago
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
