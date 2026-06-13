import logging
from datetime import date, timedelta

import cache
import telegram_bot
from airlines.google_flights import GoogleFlightsSearcher
from alerts import evaluate
from config import (
    AZUL_HUB, AZUL_DESTINATIONS, WINDOW_MIN_DAYS, WINDOW_MAX_DAYS,
    AZUL_DATE_OVERRIDES, BATCH_SIZE, CACHE_TTL_HOURS,
)

logger = logging.getLogger(__name__)

_searcher = GoogleFlightsSearcher()


def build_routes() -> list[tuple[str, str]]:
    """CNF ↔ each destination, both directions."""
    routes: list[tuple[str, str]] = []
    for dest in AZUL_DESTINATIONS:
        routes.append((AZUL_HUB, dest))
        routes.append((dest, AZUL_HUB))
    return routes


def target_dates(non_hub: str, today: date) -> list[date]:
    """Explicit override dates for the non-hub endpoint, else the rolling window."""
    override = AZUL_DATE_OVERRIDES.get(non_hub)
    if override:
        return [date.fromisoformat(s) for s in override]
    return [today + timedelta(days=n) for n in range(WINDOW_MIN_DAYS, WINDOW_MAX_DAYS + 1)]


async def run_azul_cycle() -> None:
    today = date.today()
    await cache.purge_expired()
    total_alerts = 0
    total_errors = 0

    for origin, dest in build_routes():
        non_hub = dest if origin == AZUL_HUB else origin
        dates = target_dates(non_hub, today)
        try:
            flights = await _searcher.search_dates(origin, dest, dates, BATCH_SIZE)
        except Exception as e:
            logger.warning(f"AZUL {origin}→{dest}: erro na busca: {e}")
            total_errors += 1
            continue

        alerts = evaluate(flights)
        for alert in alerts:
            if not await cache.is_cached(alert.flight):
                sent = await telegram_bot.send_azul_alert(alert.flight, alert.comparison)
                if sent:
                    await cache.save_to_cache(alert.flight, CACHE_TTL_HOURS)
                    total_alerts += 1

        logger.info(
            f"AZUL {origin}→{dest}: {len(flights)} voos, {len(alerts)} datas com Azul mais barata"
        )

    logger.info(f"CICLO AZUL CONCLUÍDO — alertas: {total_alerts} | erros: {total_errors}")
