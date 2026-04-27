import asyncio
import logging
import random
from datetime import date, timedelta
from typing import List

from playwright.async_api import Browser

from airlines.base import Flight, FlightSearcher

logger = logging.getLogger(__name__)

# NOTE: Azul Fidelidade award-flight scraping is BLOCKED at every access point found
# during discovery (scripts/azul_discover.py through azul_discover9.py):
#
# 1. azulfidelidade.com.br — DNS does not resolve; the domain is defunct.
#
# 2. www.voeazul.com.br — Azul's main booking site with the real inventory API
#    (b2c-api.voeazul.com.br). Returns HTTP 403 to headless Playwright, similar to
#    how Smiles uses Akamai Bot Manager. The b2c-api endpoint is only reachable from
#    within an authenticated browser session on www.voeazul.com.br.
#
# 3. passagens.voeazul.com.br (powered by airtrfx) — publicly accessible, but it is
#    only a marketing deals widget (vg-api.airtrfx.com/graphql). The GraphQL data
#    contains cached promotional prices without departureTime, arrivalTime, or stops
#    fields — it cannot produce valid Flight objects (per-flight inventory).
#
# _search_date() returns [] for all requests until a bypass is found.

_BOOKING_BASE = "https://www.voeazul.com.br/br/pt/home/passagens/resultados"


class AzulMilesSearcher(FlightSearcher):
    AIRLINE_NAME = "AZUL_MILES"

    async def search(self, origin: str, destination: str, departure_date: date) -> List[Flight]:
        # No browser needed — blocked at all entry points (see module docstring above).
        return []

    async def search_range(
        self, origin: str, destination: str, days_ahead: int = 30, batch_size: int = 1
    ) -> List[Flight]:
        """Returns empty list — blocked (see module docstring)."""
        return []

    async def _search_date(
        self, browser: Browser, origin: str, destination: str, departure_date: date
    ) -> List[Flight]:
        # Blocked — see module docstring.
        return []

    def _parse(
        self, data: dict, origin: str, destination: str, departure_date: date
    ) -> List[Flight]:
        """Parse template fixture format produced by Azul Fidelidade award search.

        Expected fixture structure::

            {
                "flights": [
                    {
                        "departureTime": "07:40",
                        "arrivalTime": "09:10",
                        "stops": 0,
                        "fares": [
                            {"points": 20000, "available": true},
                            ...
                        ]
                    },
                    ...
                ]
            }
        """
        flights: List[Flight] = []
        try:
            booking_url = (
                f"{_BOOKING_BASE}"
                f"?adults=1"
                f"&origin={origin}"
                f"&destination={destination}"
                f"&departureDate={departure_date.isoformat()}"
                f"&journeyType=ONE_WAY"
                f"&redemption=true"
            )
            for flight_data in data.get("flights", []):
                stops = int(flight_data.get("stops", 0))
                if stops > 1:
                    continue

                dep_time = flight_data.get("departureTime", "")
                arr_time = flight_data.get("arrivalTime", "")

                for fare in flight_data.get("fares", []):
                    if not fare.get("available", False):
                        continue
                    points = fare.get("points")
                    if points is None:
                        continue

                    flights.append(Flight(
                        origin=origin,
                        destination=destination,
                        airline=self.AIRLINE_NAME,
                        departure_date=departure_date,
                        departure_time=dep_time,
                        arrival_time=arr_time,
                        price=0.0,
                        is_direct=(stops == 0),
                        stops=stops,
                        booking_url=booking_url,
                        miles=int(points),
                    ))
        except Exception as e:
            logger.error(f"AZUL_MILES parse error: {e}", exc_info=True)
        return flights
