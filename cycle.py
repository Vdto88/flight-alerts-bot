import logging
from datetime import date

import cache
import far_cache
import history
import panel
import telegram_bot
import routing
from airlines.google_flights import GoogleFlightsSearcher
from alerts import evaluate, evaluate_threshold, evaluate_round_trip, round_trip_cache_key
from config import (
    AZUL_HUB, GROUPS, PRICE_WATCHES, ROUND_TRIP_WATCHES,
    WINDOW_MIN_DAYS, WINDOW_MAX_DAYS, WINDOW_FAR_MAX_DAYS, BATCH_SIZE, CACHE_TTL_HOURS,
)

logger = logging.getLogger(__name__)

_searcher = GoogleFlightsSearcher()
DEALS_PATH = "deals.json"
HISTORY_DIR = "history"
FAILURE_ALERT_RATIO = 0.5


class EmptyCycleError(RuntimeError):
    """Every search came back empty — the source is broken, not the market."""


async def process_round_trips(rt_ida, rt_volta, watches, all_deals, ttl_hours) -> int:
    """Evaluate each round-trip watch, send de-duped Telegram alerts, and append the
    qualifying combos to the panel snapshot. Returns the number of alerts sent."""
    sent = 0
    for w in watches:
        rt_alerts = evaluate_round_trip(rt_ida.get(w.name, []), rt_volta.get(w.name, []), w)
        for rt in rt_alerts:
            key = round_trip_cache_key(rt)
            if await cache.is_key_cached(key):
                continue
            if await telegram_bot.send_round_trip_alert(rt, w.topic_id):
                await cache.save_key(key, ttl_hours)
                sent += 1
        all_deals.extend(panel.build_round_trip_deals(rt_alerts, f"{w.name} (ida+volta)"))
    return sent


async def run_azul_cycle(include_far: bool = False) -> None:
    today = date.today()
    _searcher.reset_counters()
    logger.info(f"ciclo {'longo (até 180 dias)' if include_far else 'curto (até 120 dias)'}")
    await cache.purge_expired()
    await history.init_db()
    await history.rollup_closed(today)
    # Read once, before anything is recorded: today's prices must not skew the baseline
    # they are compared against, and every alert below shares the same picture.
    stats = await history.stats()
    route_stats = await history.route_stats()
    total_alerts = 0
    total_price_alerts = 0
    total_errors = 0
    all_deals: list[dict] = []
    rt_ida: dict[str, list] = {w.name: [] for w in ROUND_TRIP_WATCHES}
    rt_volta: dict[str, list] = {w.name: [] for w in ROUND_TRIP_WATCHES}

    for route in routing.build_routes(GROUPS, AZUL_HUB):
        dates = routing.target_dates(
            route.non_hub, today, GROUPS, WINDOW_MIN_DAYS, WINDOW_MAX_DAYS,
            PRICE_WATCHES, ROUND_TRIP_WATCHES,
            far_max=WINDOW_FAR_MAX_DAYS if include_far else None,
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
                ctx = history.context_for(alert.flight, stats, route_stats)
                if await telegram_bot.send_azul_alert(
                    alert.flight, alert.comparison, route.topic_id, context=ctx
                ):
                    await cache.save_to_cache(alert.flight, CACHE_TTL_HOURS)
                    total_alerts += 1

        # Signal 2: cheapest fare (any airline) <= a price-watch limit. Same flights, no extra queries.
        watches = [w for w in PRICE_WATCHES if w.airport == route.non_hub]
        for pa in evaluate_threshold(flights, watches):
            if not await cache.is_cached(pa.flight, kind="price"):
                ctx = history.context_for(pa.flight, stats, route_stats)
                if await telegram_bot.send_price_alert(
                    pa.flight, pa.max_price, route.topic_id, context=ctx
                ):
                    await cache.save_to_cache(pa.flight, CACHE_TTL_HOURS, kind="price")
                    total_price_alerts += 1

        group = routing.group_of(route.non_hub, GROUPS)
        region = group.name if group else route.non_hub
        all_deals.extend(panel.build_deals(flights, region, watches))

        for w in ROUND_TRIP_WATCHES:
            if route.non_hub in w.airports:
                if route.origin == AZUL_HUB:
                    rt_ida[w.name].extend(flights)
                else:
                    rt_volta[w.name].extend(flights)

        logger.info(
            f"AZUL {route.origin}→{route.destination}: {len(flights)} voos, "
            f"{len(azul_alerts)} datas com Azul mais barata"
        )

    # A healthy pass finds thousands of fares. Zero means the scraper is broken (blocked,
    # dependency drift, ...): searches swallow their own errors, so without this the run
    # would finish green and the outage would go unnoticed.
    if not all_deals:
        logger.error("CICLO VAZIO — nenhuma tarifa encontrada em nenhuma rota")
        await telegram_bot.send_health_alert(
            "Nenhuma tarifa encontrada em nenhuma rota neste ciclo. "
            "A busca no Google Flights provavelmente quebrou — veja o log do Actions."
        )
        raise EmptyCycleError("no fares found on any route")

    total_rt_alerts = await process_round_trips(
        rt_ida, rt_volta, ROUND_TRIP_WATCHES, all_deals, CACHE_TTL_HOURS
    )

    # Only what this cycle searched is recorded. Far-band records carried from the last far
    # cycle were recorded by the cycle that found them, and they are appended after every
    # alert has been evaluated, so they can never fire or re-fire one.
    searched = list(all_deals)
    if include_far:
        kept = far_cache.save(all_deals, today, WINDOW_MAX_DAYS)
        logger.info(f"datas distantes: {kept} registros guardados para os ciclos curtos")
    else:
        carried = far_cache.load_carried(all_deals, today, WINDOW_MAX_DAYS)
        all_deals.extend(carried)
        logger.info(f"datas distantes: {len(carried)} registros reaproveitados do ciclo longo")

    enriched = panel.enrich_with_history(all_deals, stats, route_stats)
    await history.record(searched)

    panel.write_deals(all_deals, DEALS_PATH)
    try:
        # The route summary is the same pre-record baseline the verdicts were computed against,
        # so the panel cannot contradict itself; only the series are re-read after recording,
        # so the charts end on today's point.
        panel.write_history_files(
            panel.build_history_payload(route_stats, await history.all_series()),
            HISTORY_DIR,
        )
    except Exception as e:
        logger.error(f"histórico do painel não gravado: {e}")
    logger.info(f"histórico: {enriched} de {len(all_deals)} registros com série de preços")
    logger.info(f"deals snapshot: {len(all_deals)} registros → {DEALS_PATH}")

    if _searcher.queries and _searcher.failures / _searcher.queries > FAILURE_ALERT_RATIO:
        await telegram_bot.send_health_alert(
            f"Mais da metade das consultas falhou neste ciclo "
            f"({_searcher.failures} de {_searcher.queries}). O painel foi atualizado com o que "
            f"deu para buscar — veja o log do Actions."
        )

    logger.info(
        f"CICLO AZUL CONCLUÍDO — alertas: {total_alerts} | "
        f"alertas de preço: {total_price_alerts} | erros: {total_errors} | "
        f"ida+volta: {total_rt_alerts} | consultas: {_searcher.queries} | falhas: {_searcher.failures}"
    )
