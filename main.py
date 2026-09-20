import asyncio
import logging
import logging.handlers
import os
from pathlib import Path
from typing import Mapping

import sys

import cache
from cycle import EmptyCycleError, run_azul_cycle


def far_dates_requested(env: Mapping[str, str]) -> bool:
    """The workflow sets SEARCH_FAR_DATES=1 on the once-a-day far cycle and on manual runs."""
    return env.get("SEARCH_FAR_DATES") == "1"


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
        await run_azul_cycle(include_far=far_dates_requested(os.environ))
    except EmptyCycleError as e:
        log.error(f"Passe falhou: {e}")
        sys.exit(1)   # red run on GitHub -> failure e-mail
    log.info("Passe concluído.")


if __name__ == "__main__":
    asyncio.run(main())
