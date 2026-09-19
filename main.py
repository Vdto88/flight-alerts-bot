import asyncio
import logging
import logging.handlers
from pathlib import Path

import sys

import cache
from cycle import EmptyCycleError, run_azul_cycle


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
    try:
        await run_azul_cycle()
    except EmptyCycleError as e:
        log.error(f"Passe falhou: {e}")
        sys.exit(1)   # red run on GitHub -> failure e-mail
    log.info("Passe concluído.")


if __name__ == "__main__":
    asyncio.run(main())
