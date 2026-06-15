"""One-off helper: print Telegram forum topic (thread) ids.

Usage:
  1. Make the bot an admin in your Forum-enabled supergroup.
  2. In EACH topic, send a short message naming it (e.g. "foz", "patagonia").
  3. Run:  python scripts/list_topics.py
  4. Map the printed thread_id to each message text, then paste the ids into the
     matching Group(topic_id=...) entries in config.py.

Requires TELEGRAM_BOT_TOKEN in the environment (or .env).
Note: if the bot has a webhook set, get_updates() will fail — remove it first
(`Bot.delete_webhook()`), or read the ids from the Telegram app's topic links.
"""
import asyncio
import os

from dotenv import load_dotenv
from telegram import Bot

load_dotenv()


async def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise SystemExit("Defina TELEGRAM_BOT_TOKEN (no .env) antes de rodar.")

    bot = Bot(token=token)
    updates = await bot.get_updates(timeout=5)
    if not updates:
        print("Nenhuma mensagem recente. Mande uma mensagem em cada tópico e rode de novo.")
        return

    # Aggregate per (chat_id, thread_id). A topic's NAME comes from the
    # "forum_topic_created" service message; otherwise fall back to any text seen.
    labels: dict[tuple[int, object], str] = {}
    for u in updates:
        msg = u.message or u.channel_post
        if not msg:
            continue
        key = (msg.chat_id, msg.message_thread_id)
        ftc = getattr(msg, "forum_topic_created", None)
        if ftc and getattr(ftc, "name", None):
            labels[key] = ftc.name                       # most authoritative
        elif key not in labels:
            labels[key] = (msg.text or "").replace("\n", " ")[:30]

    print(f"{'chat_id':>16}  {'thread_id':>10}  topico")
    print("-" * 50)
    for (chat_id, thread_id), label in sorted(
        labels.items(), key=lambda kv: (kv[0][0], kv[0][1] is not None, kv[0][1] or 0)
    ):
        print(f"{chat_id:>16}  {str(thread_id):>10}  {label}")


if __name__ == "__main__":
    asyncio.run(main())
