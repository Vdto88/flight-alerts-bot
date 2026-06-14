import logging
from datetime import date

import cache
import telegram_bot
import routing
from airlines.google_flights import GoogleFlightsSearcher
from alerts import evaluate
from config import (
    AZUL_HUB, GROUPS, WINDOW_MIN_DAYS, WINDOW_MAX_DAYS,
    BATCH_SIZE, CACHE_TTL_HOURS,
)

logger = logging.getLogger(__name__)

_searcher = GoogleFlightsSearcher()


async def run_azul_cycle() -> None:
    today = date.today()
    await cache.purge_expired()
    total_alerts = 0
    total_errors = 0

    for route in routing.build_routes(GROUPS, AZUL_HUB):
        dates = routing.target_dates(
            route.non_hub, today, GROUPS, WINDOW_MIN_DAYS, WINDOW_MAX_DAYS
        )
        try:
            flights = await _searcher.search_dates(
                route.origin, route.destination, dates, BATCH_SIZE
            )
        except Exception as e:
            logger.warning(f"AZUL {route.origin}→{route.destination}: erro na busca: {e}")
            total_errors += 1
            continue

        alerts = evaluate(flights)
        for alert in alerts:
            if not await cache.is_cached(alert.flight):
                sent = await telegram_bot.send_azul_alert(
                    alert.flight, alert.comparison, route.topic_id
                )
                if sent:
                    await cache.save_to_cache(alert.flight, CACHE_TTL_HOURS)
                    total_alerts += 1

        logger.info(
            f"AZUL {route.origin}→{route.destination}: {len(flights)} voos, "
            f"{len(alerts)} datas com Azul mais barata"
        )

    logger.info(f"CICLO AZUL CONCLUÍDO — alertas: {total_alerts} | erros: {total_errors}")
