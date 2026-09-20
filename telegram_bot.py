import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import Bot, LinkPreviewOptions
from telegram.constants import ParseMode

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID
from airlines.base import Flight
from alerts import AzulComparison, RoundTripAlert
from history import HistoryContext

logger = logging.getLogger(__name__)

_bot: Bot | None = None
_BRT = ZoneInfo("America/Sao_Paulo")


def _now_hhmm() -> str:
    """Wall-clock time in Brasília; the GitHub runner itself is on UTC."""
    return datetime.now(_BRT).strftime("%H:%M")


def get_bot() -> Bot:
    global _bot
    if _bot is None:
        _bot = Bot(token=TELEGRAM_BOT_TOKEN)
    return _bot


async def send_health_alert(text: str) -> bool:
    """Operational warning (not a fare) on the General thread. Never raises."""
    try:
        await get_bot().send_message(
            chat_id=TELEGRAM_CHANNEL_ID,
            text=f"⚠️ *BOT COM PROBLEMA*\n\n{text}\n\n⏰ {_now_hhmm()}",
            parse_mode=ParseMode.MARKDOWN,
        )
        return True
    except Exception as e:
        logger.error(f"Falha ao enviar alerta de saúde: {e}")
        return False


def _format_brl(value: float) -> str:
    return f"R$ {value:_.2f}".replace("_", "X").replace(".", ",").replace("X", ".")


_MD_SPECIALS = str.maketrans({c: "\\" + c for c in "_*`["})


def _md(text: str) -> str:
    """Escape free text for Telegram's legacy Markdown. Airline names come from Google; one
    stray '_' or '*' opens an entity that never closes and the whole message gets a 400."""
    return text.translate(_MD_SPECIALS)


def _stops_label(flight: Flight) -> str:
    if flight.is_direct or flight.stops == 0:
        return "Direto"
    return f"{flight.stops} parada" + ("s" if flight.stops > 1 else "")


FLAT_PCT = 3    # same noise threshold the panel uses


def format_context_line(ctx: HistoryContext | None) -> str:
    """One line placing the fare against its own history; empty when there is none."""
    if ctx is None:
        return ""
    base = "da média da rota" if ctx.scope == "rota" else f"da média de {ctx.window_days} dias"
    if abs(ctx.delta_pct) <= FLAT_PCT:
        line = "➖ na média da rota" if ctx.scope == "rota" else f"➖ na média de {ctx.window_days} dias"
    elif ctx.delta_pct < 0:
        line = f"📉 {abs(ctx.delta_pct)}% abaixo {base}"
    else:
        line = f"📈 {ctx.delta_pct}% acima {base}"
    if ctx.is_lowest and ctx.since:
        _y, m, d = ctx.since.split("-")
        line += f" · menor preço desde {d}/{m}"
    return line + "\n"


def format_azul_alert(flight: Flight, comparison: AzulComparison,
                      context: HistoryContext | None = None) -> str:
    dep_date = flight.departure_date.strftime("%d/%m/%Y")
    now_str = _now_hhmm()
    return (
        f"🔵 *AZUL É A MAIS BARATA*\n\n"
        f"🛫 {flight.origin} → {flight.destination}\n"
        f"💰 {_format_brl(flight.price)}  (Azul)\n"
        f"📊 vs {_format_brl(comparison.competitor_price)} ({_md(comparison.competitor)}) "
        f"— economia de {_format_brl(comparison.savings)}\n"
        f"{format_context_line(context)}"
        f"📅 {dep_date} • {flight.departure_time} → {flight.arrival_time}\n"
        f"🏢 Azul • {_stops_label(flight)}\n"
        f"🔗 [Reservar agora]({flight.booking_url})\n\n"
        f"⏰ Detectado às {now_str}"
    )


async def send_azul_alert(flight: Flight, comparison: AzulComparison,
                          topic_id: int | None = None,
                          context: HistoryContext | None = None) -> bool:
    """Returns True if the alert was sent, False otherwise (so the caller only
    marks it as seen on success — a failed send must be retried next cycle).
    Posts to the forum topic `topic_id` when given; if that send fails (topic
    deleted, chat isn't a forum, ...) it retries once on the General thread."""
    message = format_azul_alert(flight, comparison, context)
    try:
        bot = get_bot()
    except Exception as e:
        logger.error(f"Falha ao criar bot Telegram: {e}")
        return False

    async def _send(thread_id: int | None) -> None:
        await bot.send_message(
            chat_id=TELEGRAM_CHANNEL_ID,
            text=message,
            parse_mode=ParseMode.MARKDOWN,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
            message_thread_id=thread_id,
        )

    try:
        await _send(topic_id)
    except Exception as e:
        if topic_id is None:
            logger.error(f"Falha ao enviar alerta Azul: {e}")
            return False
        logger.warning(f"Tópico {topic_id} falhou, tentando Geral: {e}")
        try:
            await _send(None)
        except Exception as e2:
            logger.error(f"Falha ao enviar alerta Azul (Geral): {e2}")
            return False

    logger.info(
        f"Alerta Azul enviado: {flight.origin}→{flight.destination} "
        f"R${flight.price:.2f} (vs {comparison.competitor} R${comparison.competitor_price:.2f}) "
        f"{flight.departure_date}"
    )
    return True


def format_price_alert(flight: Flight, max_price: float,
                       context: HistoryContext | None = None) -> str:
    dep_date = flight.departure_date.strftime("%d/%m/%Y")
    now_str = _now_hhmm()
    return (
        f"✈️ *PASSAGEM BARATA DETECTADA*\n\n"
        f"🛫 {flight.origin} → {flight.destination}\n"
        f"💰 {_format_brl(flight.price)}\n"
        f"🎯 abaixo do seu limite de {_format_brl(max_price)}\n"
        f"{format_context_line(context)}"
        f"📅 {dep_date} • {flight.departure_time} → {flight.arrival_time}\n"
        f"🏢 {_md(flight.airline)} • {_stops_label(flight)}\n"
        f"🔗 [Reservar agora]({flight.booking_url})\n\n"
        f"⏰ Detectado às {now_str}"
    )


async def send_price_alert(flight: Flight, max_price: float,
                           topic_id: int | None = None,
                           context: HistoryContext | None = None) -> bool:
    """Returns True only on a successful send. Posts to the forum topic `topic_id`;
    if that fails it retries once on the General thread."""
    message = format_price_alert(flight, max_price, context)
    try:
        bot = get_bot()
    except Exception as e:
        logger.error(f"Falha ao criar bot Telegram: {e}")
        return False

    async def _send(thread_id: int | None) -> None:
        await bot.send_message(
            chat_id=TELEGRAM_CHANNEL_ID,
            text=message,
            parse_mode=ParseMode.MARKDOWN,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
            message_thread_id=thread_id,
        )

    try:
        await _send(topic_id)
    except Exception as e:
        if topic_id is None:
            logger.error(f"Falha ao enviar alerta de preço: {e}")
            return False
        logger.warning(f"Tópico {topic_id} falhou, tentando Geral: {e}")
        try:
            await _send(None)
        except Exception as e2:
            logger.error(f"Falha ao enviar alerta de preço (Geral): {e2}")
            return False

    logger.info(
        f"Alerta de preço enviado: {flight.origin}→{flight.destination} "
        f"{flight.airline} R${flight.price:.2f} (limite R${max_price:.2f}) {flight.departure_date}"
    )
    return True


def format_round_trip_alert(rt: RoundTripAlert) -> str:
    ida_d = rt.ida.departure_date.strftime("%d/%m/%Y")
    volta_d = rt.volta.departure_date.strftime("%d/%m/%Y")
    now_str = _now_hhmm()
    return (
        f"🌍 *IDA+VOLTA {rt.watch_name.upper()} < {_format_brl(rt.max_total)}*\n\n"
        f"🛫 Ida:   {rt.ida.origin} → {rt.ida.destination} · {ida_d} · "
        f"{_md(rt.ida.airline)} · {_format_brl(rt.ida.price)}\n"
        f"🛬 Volta: {rt.volta.origin} → {rt.volta.destination} · {volta_d} · "
        f"{_md(rt.volta.airline)} · {_format_brl(rt.volta.price)}\n"
        f"🧳 Estadia: {rt.stay_days} dias\n"
        f"💰 Total: {_format_brl(rt.total)}  (teto {_format_brl(rt.max_total)})\n"
        f"🔗 [Reservar ida]({rt.ida.booking_url}) · [Reservar volta]({rt.volta.booking_url})\n\n"
        f"⏰ Detectado às {now_str}"
    )


async def send_round_trip_alert(rt: RoundTripAlert, topic_id: int | None = None) -> bool:
    """Returns True only on a successful send. Posts to `topic_id`; on failure retries
    once on the General thread."""
    message = format_round_trip_alert(rt)
    try:
        bot = get_bot()
    except Exception as e:
        logger.error(f"Falha ao criar bot Telegram: {e}")
        return False

    async def _send(thread_id: int | None) -> None:
        await bot.send_message(
            chat_id=TELEGRAM_CHANNEL_ID,
            text=message,
            parse_mode=ParseMode.MARKDOWN,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
            message_thread_id=thread_id,
        )

    try:
        await _send(topic_id)
    except Exception as e:
        if topic_id is None:
            logger.error(f"Falha ao enviar alerta ida+volta: {e}")
            return False
        logger.warning(f"Tópico {topic_id} falhou, tentando Geral: {e}")
        try:
            await _send(None)
        except Exception as e2:
            logger.error(f"Falha ao enviar alerta ida+volta (Geral): {e2}")
            return False

    logger.info(
        f"Alerta ida+volta enviado: {rt.ida.origin}→{rt.ida.destination} + "
        f"{rt.volta.origin}→{rt.volta.destination} R${rt.total:.2f} "
        f"({rt.stay_days}d) {rt.ida.departure_date}"
    )
    return True
