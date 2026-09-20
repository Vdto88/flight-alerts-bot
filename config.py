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


@dataclass(frozen=True)
class RoundTripWatch:
    name: str                    # display/topic label, e.g. "Europa"
    airports: tuple[str, ...]    # pool: ida-destination and volta-origin
    depart_window: SearchWindow  # allowed ida departure dates
    stay_min: int                # min stay in days
    stay_max: int                # max stay in days (never exceeded)
    max_total: float             # BRL; alert when ida+volta <= this
    topic_id: int | None         # Telegram topic; None = General


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


@dataclass(frozen=True)
class Airport:
    cidade: str
    uf: str | None    # Brazilian state; None abroad
    pais: str


# Where each airport is, for the panel. Groups above only pick the Telegram topic, so
# airports sharing a topic (FLN + POA under "Sul") still show up as separate places.
# tests/test_airports.py fails when a searched airport is missing here.
AIRPORTS: dict[str, Airport] = {
    "CNF": Airport("Belo Horizonte", "MG", "Brasil"),
    "GIG": Airport("Rio de Janeiro", "RJ", "Brasil"),
    "SDU": Airport("Rio de Janeiro", "RJ", "Brasil"),
    "CGH": Airport("São Paulo", "SP", "Brasil"),
    "SJK": Airport("São José dos Campos", "SP", "Brasil"),
    "SLZ": Airport("São Luís", "MA", "Brasil"),
    "FLN": Airport("Florianópolis", "SC", "Brasil"),
    "NVT": Airport("Navegantes", "SC", "Brasil"),
    "POA": Airport("Porto Alegre", "RS", "Brasil"),
    "IGU": Airport("Foz do Iguaçu", "PR", "Brasil"),
    "FTE": Airport("El Calafate", None, "Argentina"),
    "BRC": Airport("Bariloche", None, "Argentina"),
    "PNT": Airport("Puerto Natales", None, "Chile"),
    "PMC": Airport("Puerto Montt", None, "Chile"),
    "PUQ": Airport("Punta Arenas", None, "Chile"),
    "SCL": Airport("Santiago", None, "Chile"),
    "LIS": Airport("Lisboa", None, "Portugal"),
    "OPO": Airport("Porto", None, "Portugal"),
    "MAD": Airport("Madri", None, "Espanha"),
    "BCN": Airport("Barcelona", None, "Espanha"),
    "FCO": Airport("Roma", None, "Itália"),
    "MXP": Airport("Milão", None, "Itália"),
    "CDG": Airport("Paris", None, "França"),
    "ORY": Airport("Paris", None, "França"),
}

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
ROUND_TRIP_WATCHES: list[RoundTripWatch] = [
    RoundTripWatch(
        name="Europa",
        airports=("LIS", "OPO", "MAD", "BCN", "FCO", "MXP", "CDG", "ORY"),
        depart_window=SearchWindow(date(2027, 2, 1), date(2027, 5, 31)),
        stay_min=13, stay_max=15,
        max_total=3000.0,
        topic_id=None,   # General
    ),
]

# Rolling window of departure dates to check, in days from today.
WINDOW_MIN_DAYS: int = 30
WINDOW_MAX_DAYS: int = 120

# Far band: days WINDOW_MAX_DAYS+1 .. WINDOW_FAR_MAX_DAYS, searched once a day (the cycle the
# workflow flags with SEARCH_FAR_DATES=1). Fares that far out move slowly.
WINDOW_FAR_MAX_DAYS: int = 180

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
