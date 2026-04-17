import asyncio
import logging
import time
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

import cache
import telegram_bot
from airlines.base import FlightSearcher
from airlines.gol import GolSearcher
from airlines.latam import LatamSearcher
from airlines.azul import AzulSearcher
from airlines.google_flights import GoogleFlightsSearcher
from config import ROUTES, CYCLE_MINUTES, CACHE_TTL_HOURS, SEARCH_DAYS_AHEAD, BATCH_SIZE

logger = logging.getLogger(__name__)

SEARCHERS: dict[str, FlightSearcher] = {
    "GOL": GolSearcher(),
    "LATAM": LatamSearcher(),
    "AZUL": AzulSearcher(),
}

google_searcher = GoogleFlightsSearcher()

_AIRLINE_ALIASES: dict[str, list[str]] = {
    "GOL":   ["gol"],
    "LATAM": ["latam"],
    "AZUL":  ["azul"],
}


def _matches_airline(flight_airline: str, expected: str) -> bool:
    aliases = _AIRLINE_ALIASES.get(expected.upper(), [expected.lower()])
    name_lower = flight_airline.lower()
    return any(alias in name_lower for alias in aliases)


async def run_cycle() -> None:
    start = time.monotonic()
    total_candidates = 0
    total_alerts = 0
    total_errors = 0

    logger.info(f"CICLO INICIADO — {len(ROUTES)} rotas")
    await cache.purge_expired()

    _gf_cache: dict[tuple, list] = {}

    for route in ROUTES:
        origin = route["from"]
        dest = route["to"]
        threshold = route["threshold"]
        airline_names = [n for n in route["airlines"] if n in SEARCHERS]

        tasks = [SEARCHERS[name].search_range(origin, dest, SEARCH_DAYS_AHEAD, BATCH_SIZE) for name in airline_names]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for name, result in zip(airline_names, results):
            if isinstance(result, Exception):
                logger.warning(f"ERRO {name}/{origin}→{dest}: {result}")
                total_errors += 1
                result = []

            if not result:
                logger.info(f"{name}/{origin}→{dest}: fallback para Google Flights")
                try:
                    key = (origin, dest)
                    if key not in _gf_cache:
                        _gf_cache[key] = await google_searcher.search_range(origin, dest, SEARCH_DAYS_AHEAD, BATCH_SIZE)
                    gf_flights = _gf_cache[key]
                    result = [f for f in gf_flights if _matches_airline(f.airline, name)]
                except Exception as e:
                    logger.warning(f"{name}/{origin}→{dest}: fallback Google Flights falhou: {e}")
                    total_errors += 1

            below = [f for f in result if f.price < threshold and f.stops <= 1]
            logger.info(
                f"{name}/{origin}→{dest}: {len(result)} voos encontrados, {len(below)} abaixo do threshold"
            )
            total_candidates += len(below)

            for flight in below:
                if not await cache.is_cached(flight):
                    await telegram_bot.send_alert(flight)
                    await cache.save_to_cache(flight, CACHE_TTL_HOURS)
                    total_alerts += 1

    elapsed = time.monotonic() - start
    logger.info(
        f"CICLO CONCLUÍDO — {elapsed:.0f}s | rotas: {len(ROUTES)} | "
        f"candidatos: {total_candidates} | alertas: {total_alerts} | erros: {total_errors}"
    )


def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_cycle,
        trigger="interval",
        minutes=CYCLE_MINUTES,
        next_run_time=datetime.now(),
        id="flight_cycle",
    )
    return scheduler
