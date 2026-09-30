import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import config
import routing
from miles import providers
from miles.transport import ClientUnavailable

log = logging.getLogger(__name__)
PROVIDERS = {"azul": providers.azul, "latam": providers.latam, "gol": providers.gol}
NAMES = {"azul": "Azul Fidelidade", "latam": "LATAM Pass", "gol": "GOL · Smiles"}


def search_plan(today, include_far=False):
    routes = routing.build_routes(config.GROUPS, config.AZUL_HUB)
    return {(r.origin, r.destination): {d.isoformat() for d in routing.target_dates(
        r.non_hub, today, config.GROUPS, config.WINDOW_MIN_DAYS, config.WINDOW_MAX_DAYS,
        watches=config.PRICE_WATCHES, rt_watches=config.ROUND_TRIP_WATCHES,
        far_max=config.WINDOW_FAR_MAX_DAYS if include_far else None)} for r in routes}


def select(offers, plan):
    selected = {}
    for offer in offers:
        days = plan.get((offer.origin, offer.destination), set())
        if offer.departure_date not in days:
            continue
        if offer.return_date and offer.return_date not in days:
            continue
        if offer.key not in selected or offer.points < selected[offer.key].points:
            selected[offer.key] = offer
    return sorted(selected.values(), key=lambda o: (o.points, o.departure_date))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


async def send_alert(offer, previous, topic):
    import telegram_bot
    text = (f"✈️ BAIXOU EM MILHAS · {NAMES[offer.airline]}\n\n"
            f"{offer.origin} → {offer.destination}\n"
            f"Ida: {offer.departure_date}"
            + (f" · volta: {offer.return_date}" if offer.return_date else " · por trecho")
            + f"\nDe {previous:,} para {offer.points:,} pontos/milhas\n"
            f"{offer.condition} · {offer.cabin}\n\n"
            "Oferta publicada; confirme disponibilidade e taxas antes de emitir.\n"
            f"{offer.url}")
    try:
        await telegram_bot.get_bot().send_message(chat_id=config.TELEGRAM_CHANNEL_ID,
            message_thread_id=topic, text=text)
        return True
    except Exception as exc:
        log.warning("Mileage delivery failed (%s)", type(exc).__name__)
        return False


async def run(*, include_far=False, notify=False, state_path=Path("data/miles-state.json"),
              output_path=Path("miles.json"), plan=None, provider_map=None, sender=send_alert):
    now = datetime.now(timezone.utc)
    today = now.astimezone(ZoneInfo("America/Sao_Paulo")).date()
    plan = plan if plan is not None else search_plan(today, include_far)
    try:
        state = json.loads(Path(state_path).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        state = {"prices": {}, "sent": {}}
    cutoff = (now - timedelta(hours=48)).isoformat()
    prices = {k: v for k, v in state.get("prices", {}).items() if v["seen_at"] >= cutoff}
    sent_cutoff = (now - timedelta(hours=24)).isoformat()
    sent = {k: v for k, v in state.get("sent", {}).items() if v >= sent_cutoff}
    report = {"generated_at": now.isoformat(), "programs": {},
              "notice": "Ofertas publicadas, com cobertura parcial de datas. Disponibilidade e taxas precisam de confirmação.",
              "alert_rule": "Queda em relação à última coleta da mesma oferta; primeira coleta estabelece a referência."}
    delivered = 0
    for airline, provider in (provider_map or PROVIDERS).items():
        try:
            rows, health = await asyncio.to_thread(provider, plan)
            offers = select(rows, plan) if health["status"] != "error" else []
            report["programs"][airline] = {**health, "name": NAMES[airline],
                "fetched_at": datetime.now(timezone.utc).isoformat(), "offers": [o.payload() for o in offers]}
            log.info("%s: %s offers, status=%s", airline, len(offers), health["status"])
            for offer in offers:
                previous = prices.get(offer.key)
                delivery_key = offer.key + ":" + str(offer.points)
                fell = previous is not None and offer.points < previous["points"]
                if notify and fell and delivery_key not in sent:
                    # Preserve the previous reference on failed/capped delivery so
                    # the next run retries. A failed feed never sends alerts.
                    group = routing.group_of(offer.destination if offer.origin == config.AZUL_HUB
                                             else offer.origin, config.GROUPS)
                    if delivered >= 20 or not await sender(offer, previous["points"],
                                                          group.topic_id if group else None):
                        continue
                    sent[delivery_key] = now.isoformat()
                    delivered += 1
                prices[offer.key] = {"points": offer.points, "seen_at": now.isoformat()}
        except Exception as exc:
            log.warning("%s public source failed (%s)", airline, type(exc).__name__)
            report["programs"][airline] = {"name": NAMES[airline], "status": "error",
                "fetched_at": datetime.now(timezone.utc).isoformat(), "offers": [],
                "notice": "Coleta de milhas não configurada neste ambiente." if isinstance(exc, ClientUnavailable)
                else "Fonte indisponível nesta coleta. Não significa ausência de voos."}
    # A local preview doesn't change the production baseline or acknowledge alerts.
    if notify:
        write_json(state_path, {"prices": prices, "sent": sent})
    report["generated_at"] = datetime.now(timezone.utc).isoformat()
    write_json(output_path, report)
    return report
