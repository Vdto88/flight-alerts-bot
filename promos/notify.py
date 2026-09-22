"""Telegram side of the promotions: one message per accepted post, to the topic of its kind.

Unlike the fare alerts, a promotion whose topic is not configured is not sent at all, and a
failed send does not fall back to the General thread: the caller retries it next hour.
"""
import asyncio
import logging
from zoneinfo import ZoneInfo

from telegram import LinkPreviewOptions
from telegram.constants import ParseMode
from telegram.error import RetryAfter

import config
from promos.classify import Classification
from promos.feeds import FeedItem
from telegram_bot import _md, get_bot

logger = logging.getLogger(__name__)

SENT, FAILED, SKIPPED = "sent", "failed", "skipped"
SUMMARY_LIMIT = 200
MAX_FLOOD_WAIT_SECONDS = 30.0
_BRT = ZoneInfo("America/Sao_Paulo")


def _cut(text: str, limit: int = SUMMARY_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(" ,.;:") + "…"


def _tag_line(c: Classification) -> str:
    if c.kind == "miles":
        parts = (("🟢 saindo de BH",) if c.from_bh else ()) + c.programs + c.destinations
        return "🏷️ " + " · ".join(parts)
    parts = []
    if c.from_bh:
        parts.append("🟢 saindo de BH")
    if c.destinations:
        parts.append(", ".join(c.destinations))
    if c.origin_unknown:
        parts.append("origem não informada")
    return "📍 " + " · ".join(parts)


def format_promo(item: FeedItem, c: Classification) -> str:
    when = item.published_at.astimezone(_BRT).strftime("%d/%m %H:%M")
    lines = [
        f"{'💳' if c.kind == 'miles' else '✈️'} *{_md(item.title)}*",
        _md(_tag_line(c)),
        f"📰 {_md(item.source)} · {when}",
    ]
    if item.summary:
        lines.append(_md(_cut(item.summary)))
    if item.link.startswith("https://"):
        # A ")" would close the Markdown link early.
        lines.append(f"🔗 [Ver a promoção]({item.link.replace(')', '%29')})")
    return "\n".join(lines)


def _topic_for(c: Classification) -> int | None:
    return config.PROMO_TOPIC_MILES if c.kind == "miles" else config.PROMO_TOPIC_FARES


async def send_promo(item: FeedItem, c: Classification) -> str:
    topic = _topic_for(c)
    if topic is None:
        return SKIPPED
    text = format_promo(item, c)

    async def _send() -> None:
        await get_bot().send_message(
            chat_id=config.TELEGRAM_CHANNEL_ID, text=text, parse_mode=ParseMode.MARKDOWN,
            link_preview_options=LinkPreviewOptions(is_disabled=True), message_thread_id=topic,
        )

    try:
        try:
            await _send()
        except RetryAfter as e:
            delay = e.retry_after
            seconds = delay.total_seconds() if hasattr(delay, "total_seconds") else float(delay)
            await asyncio.sleep(min(seconds, MAX_FLOOD_WAIT_SECONDS))
            await _send()
    except Exception as e:
        logger.error(f"Falha ao enviar promoção ({item.title}): {e}")
        return FAILED
    logger.info(f"Promoção enviada ao tópico {topic}: {item.title}")
    return SENT
