import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID: str = os.environ.get("TELEGRAM_CHANNEL_ID", "")

# --- Azul-cheapest alert ---
AZUL_HUB: str = "CNF"
AZUL_DESTINATIONS: list[str] = [
    # Domestic
    "GIG", "SDU", "CGH", "SSA", "SLZ", "IGU", "FLN", "NVT",
    # Patagonia / Chile / Argentina (rarely fire — kept on purpose)
    "FTE", "PNT", "PMC", "PUQ", "SCL", "BRC",
]

# Rolling window of departure dates to check, in days from today.
WINDOW_MIN_DAYS: int = 30
WINDOW_MAX_DAYS: int = 90

# Optional: pin explicit ISO dates for a destination instead of the rolling window.
# e.g. {"SCL": ["2026-12-15", "2026-12-16"]}
AZUL_DATE_OVERRIDES: dict[str, list[str]] = {}

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
