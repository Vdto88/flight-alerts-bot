import asyncio
import logging
import logging.handlers
from pathlib import Path

import cache
from scheduler import create_scheduler


def setup_logging() -> None:
    Path("logs").mkdir(exist_ok=True)
    fmt = logging.Formatter("[%(asctime)s] %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    console = logging.StreamHandler()
    console.setFormatter(fmt)

    file_handler = logging.handlers.TimedRotatingFileHandler(
        "logs/bot.log", when="midnight", backupCount=7, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(console)
    root.addHandler(file_handler)


async def main() -> None:
    setup_logging()
    log = logging.getLogger(__name__)

    await cache.init_db()
    scheduler = create_scheduler()
    scheduler.start()
    log.info("Bot iniciado. Pressione Ctrl+C para parar.")

    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        log.info("Bot encerrado.")


if __name__ == "__main__":
    asyncio.run(main())
