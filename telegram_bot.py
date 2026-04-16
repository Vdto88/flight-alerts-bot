import logging
from datetime import datetime

from telegram import Bot, LinkPreviewOptions
from telegram.constants import ParseMode

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID
from airlines.base import Flight

logger = logging.getLogger(__name__)

_bot: Bot | None = None


def get_bot() -> Bot:
    global _bot
    if _bot is None:
        _bot = Bot(token=TELEGRAM_BOT_TOKEN)
    return _bot


def format_alert(flight: Flight) -> str:
    dep_date = flight.departure_date.strftime("%d/%m/%Y")
    # Brazilian number format: 1.234,56
    price_str = f"R$ {flight.price:_.2f}".replace("_", "X").replace(".", ",").replace("X", ".")
    stops_str = "Direto" if flight.is_direct else f"{flight.stops} parada"
    now_str = datetime.now().strftime("%H:%M")

    return (
        f"✈️ *PASSAGEM BARATA DETECTADA*\n\n"
        f"🛫 {flight.origin} → {flight.destination}\n"
        f"💰 {price_str}\n"
        f"📅 {dep_date} • {flight.departure_time} → {flight.arrival_time}\n"
        f"🏢 {flight.airline} • {stops_str}\n"
        f"🔗 [Reservar agora]({flight.booking_url})\n\n"
        f"⏰ Detectado às {now_str}"
    )


async def send_alert(flight: Flight) -> None:
    bot = get_bot()
    message = format_alert(flight)
    try:
        await bot.send_message(
            chat_id=TELEGRAM_CHANNEL_ID,
            text=message,
            parse_mode=ParseMode.MARKDOWN,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
        logger.info(
            f"Alerta enviado: {flight.airline}/{flight.origin}→{flight.destination} "
            f"R${flight.price:.2f} {flight.departure_date}"
        )
    except Exception as e:
        logger.error(f"Falha ao enviar alerta Telegram: {e}")
