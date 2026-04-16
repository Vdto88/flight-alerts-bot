import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID: str = os.environ.get("TELEGRAM_CHANNEL_ID", "")
GOL_API_KEY: str = os.getenv("GOL_API_KEY", "aaa-bbb")

ROUTES = [
    {"from": "CNF", "to": "GRU", "threshold": 350,  "airlines": ["GOL", "LATAM", "AZUL"]},
    {"from": "GRU", "to": "LIS", "threshold": 2000, "airlines": ["LATAM", "GOL"]},
    {"from": "GRU", "to": "MIA", "threshold": 1500, "airlines": ["LATAM", "GOL"]},
    {"from": "CNF", "to": "SSA", "threshold": 400,  "airlines": ["GOL", "AZUL"]},
]

SEARCH_DAYS_AHEAD: int = 60
BATCH_SIZE: int = 7
CYCLE_MINUTES: int = 45
CACHE_TTL_HOURS: int = 24
REQUEST_TIMEOUT: float = 15.0
REQUEST_RETRIES: int = 2
REQUEST_RETRY_BACKOFF: float = 2.0
