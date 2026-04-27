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

MILES_ROUTES = [
    {"from": "CNF", "to": "IGU", "miles_threshold": 15000, "program": "SMILES"},
    {"from": "IGU", "to": "CNF", "miles_threshold": 15000, "program": "SMILES"},
    {"from": "CNF", "to": "IGU", "miles_threshold": 20000, "program": "AZUL_MILES"},
    {"from": "IGU", "to": "CNF", "miles_threshold": 20000, "program": "AZUL_MILES"},
]

# 30 dias é suficiente — cada data requer uma sessão Playwright (~5–10s)
# 30 datas × 4 rotas × ~7s = ~14 min por ciclo, dentro do MILES_CYCLE_MINUTES
MILES_DAYS_AHEAD: int = 30
MILES_CYCLE_MINUTES: int = 60
