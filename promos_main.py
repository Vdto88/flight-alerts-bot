"""One pass over the promotion feeds: fetch, classify, tell Telegram, write the panel payload.

Run hourly by .github/workflows/promos.yml. Exits 1 only when every feed failed, so a single
blog being down does not turn the run red.
"""
import asyncio
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import config
import telegram_bot
from promos import feeds, notify, state
from promos.classify import classify

logger = logging.getLogger(__name__)


async def run_cycle(now: datetime | None = None, state_path: Path = state.STATE_PATH,
                    payload_path: Path = state.PAYLOAD_PATH, transport=None) -> int:
    now = now or datetime.now(timezone.utc)
    st = state.load(state_path)
    items, feed_ok = await feeds.fetch_all(config.PROMO_FEEDS, now=now, transport=transport)

    for source, ok in feed_ok.items():
        if st.record_feed_result(source, ok):
            await telegram_bot.send_health_alert(
                f"O feed de promoções {source} falhou em {state.HEALTH_AFTER} ciclos seguidos. "
                "Veja o log do workflow de promoções."
            )

    # With no state yet every post in the feeds is new; only the recent ones are worth a message.
    seed_floor = now - timedelta(hours=config.PROMO_SEED_MAX_AGE_HOURS)
    accepted = sent = held = 0
    for item in sorted(items, key=lambda i: i.published_at):
        if st.is_seen(item.guid):
            continue
        c, reason = classify(item)
        logger.info(f"promo {reason} | {item.source} | {item.title}")
        if c is None:
            st.mark_seen(item.guid, now)
            continue
        accepted += 1
        st.add_promo(item, c)
        if st.seeding and item.published_at < seed_floor:
            st.mark_seen(item.guid, now)
            continue
        if sent >= config.PROMO_MAX_MESSAGES_PER_CYCLE:
            held += 1
            st.mark_seen(item.guid, now)
            continue
        result = await notify.send_promo(item, c)
        if result == notify.FAILED:
            if st.record_attempt(item.guid) >= state.MAX_ATTEMPTS:
                logger.error(f"promoção desistida após {state.MAX_ATTEMPTS} tentativas: {item.title}")
                st.mark_seen(item.guid, now)
            continue
        if result == notify.SKIPPED:
            logger.warning(f"tópico não configurado, promoção só no painel: {item.title}")
        else:
            sent += 1
        st.mark_seen(item.guid, now)

    state.save(st, now, state_path, payload_path)
    down = [s for s, ok in feed_ok.items() if not ok]
    logger.info(
        f"CICLO PROMOS CONCLUÍDO — itens: {len(items)} | aceitas: {accepted} | enviadas: {sent} | "
        f"acima do teto: {held} | feeds fora: {len(down)}{' (' + ', '.join(down) + ')' if down else ''}"
    )
    return 1 if feed_ok and len(down) == len(feed_ok) else 0


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S")
    sys.exit(asyncio.run(run_cycle()))


if __name__ == "__main__":
    main()
