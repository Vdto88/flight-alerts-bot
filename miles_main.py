"""Mileage cycle. Local use is a preview; --notify explicitly enables Telegram."""
import argparse
import asyncio
import logging
import os

from miles.cycle import run

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notify", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("primp").setLevel(logging.WARNING)
    asyncio.run(run(include_far=os.environ.get("SEARCH_FAR_DATES") == "1", notify=args.notify))
