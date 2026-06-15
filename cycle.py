import logging
from datetime import date

import cache
import telegram_bot
import routing
from airlines.google_flights import GoogleFlightsSearcher
from alerts import evaluate, evaluate_threshold
from config import (
    AZUL_HUB, GROUPS, PRICE_WATCHES, WINDOW_MIN_DAYS, WINDOW_MAX_DAYS,
    BATCH_SIZE, CACHE_TTL_HOURS,
)

logger = logging.getLogger(__name__)

_searcher = GoogleFlightsSearcher()


async def run_azul_cycle() -> None:
    today = date.today()
    await cache.purge_expired()
    total_alerts = 0
    total_price_alerts = 0
    total_errors = 0

    for route in routing.build_routes(GROUPS, AZUL_HUB):
        dates = routing.target_dates(
            route.non_hub, today, GROUPS, WINDOW_MIN_DAYS, WINDOW_MAX_DAYS, PRICE_WATCHES
        )
        try:
            flights = await _searcher.search_dates(
                route.origin, route.destination, dates, BATCH_SIZE
            )
        except Exception as e:
            logger.warning(f"AZUL {route.origin}→{route.destination}: erro na busca: {e}")
            total_errors += 1
            continue

        # Signal 1: Azul is the cheapest airline on a date.
        azul_alerts = evaluate(flights)
        for alert in azul_alerts:
            if not await cache.is_cached(alert.flight):
                if await telegram_bot.send_azul_alert(alert.flight, alert.comparison, route.topic_id):
                    await cache.save_to_cache(alert.flight, CACHE_TTL_HOURS)
                    total_alerts += 1

        # Signal 2: cheapest fare (any airline) <= a price-watch limit. Same flights, no extra queries.
        watches = [w for w in PRICE_WATCHES if w.airport == route.non_hub]
        for pa in evaluate_threshold(flights, watches):
            if not await cache.is_cached(pa.flight, kind="price"):
                if await telegram_bot.send_price_alert(pa.flight, pa.max_price, route.topic_id):
                    await cache.save_to_cache(pa.flight, CACHE_TTL_HOURS, kind="price")
                    total_price_alerts += 1

        logger.info(
            f"AZUL {route.origin}→{route.destination}: {len(flights)} voos, "
            f"{len(azul_alerts)} datas com Azul mais barata"
        )

    logger.info(
        f"CICLO AZUL CONCLUÍDO — alertas: {total_alerts} | "
        f"alertas de preço: {total_price_alerts} | erros: {total_errors}"
    )
