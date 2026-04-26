import asyncio
import logging
import os
import random
from datetime import date, timedelta
from typing import List, Optional

from playwright.async_api import async_playwright, Browser

from airlines.base import Flight, FlightSearcher

logger = logging.getLogger(__name__)

# NOTE: The historical Smiles URL /emissao-passagem-com-milhas now returns 404.
# The active search page is /passagens-aereas. However, loading this URL
# does not automatically trigger the flight search API — the SPA requires
# form interaction (fill + submit). The current implementation captures any
# JSON intercepted from flightavailability-prd.smiles.com.br; if no response
# is captured, it returns []. A future improvement should add form-fill logic.
_SEARCH_BASE = "https://www.smiles.com.br/passagens-aereas"
_API_HOST = "flightavailability-prd.smiles.com.br"


def _is_headless() -> bool:
    return os.getenv("PLAYWRIGHT_HEADLESS", "true").lower() != "false"


def _parse_time(iso_str: str) -> str:
    """Extrai 'HHhMM' de '2026-07-15T07:40:00'."""
    if not iso_str or "T" not in iso_str:
        return ""
    time_part = iso_str.split("T")[1][:5]  # "07:40"
    return time_part.replace(":", "h")


class SmilesMilesSearcher(FlightSearcher):
    AIRLINE_NAME = "SMILES"

    async def search(self, origin: str, destination: str, departure_date: date) -> List[Flight]:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=_is_headless())
            try:
                return await self._search_date(browser, origin, destination, departure_date)
            except Exception as e:
                logger.warning(f"SMILES/{origin}→{destination} {departure_date}: {e}")
                return []
            finally:
                await browser.close()

    async def search_range(
        self, origin: str, destination: str, days_ahead: int = 30, batch_size: int = 1
    ) -> List[Flight]:
        """Abre um único browser e reutiliza para todas as datas (mais eficiente)."""
        today = date.today()
        dates = [today + timedelta(days=i) for i in range(1, days_ahead + 1)]
        all_flights: List[Flight] = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=_is_headless())
            try:
                for d in dates:
                    flights = await self._search_date(browser, origin, destination, d)
                    all_flights.extend(flights)
                    await asyncio.sleep(random.uniform(2, 4))
            except Exception as e:
                logger.warning(f"SMILES/search_range {origin}→{destination}: {e}")
            finally:
                await browser.close()

        return all_flights

    async def _search_date(
        self, browser: Browser, origin: str, destination: str, departure_date: date
    ) -> List[Flight]:
        page = await browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        captured: list = []

        async def handle_response(response):
            if _API_HOST in response.url and response.status == 200:
                try:
                    data = await response.json()
                    captured.append(data)
                except Exception:
                    pass

        page.on("response", handle_response)

        try:
            date_str = departure_date.strftime("%d/%m/%Y")
            url = (
                f"{_SEARCH_BASE}"
                f"?originAirportCode={origin}"
                f"&destinationAirportCode={destination}"
                f"&departureDate={date_str}"
                f"&adults=1&children=0&infants=0"
                f"&tripType=2&cabinType=all"
            )
            await page.goto(url, timeout=30000)
            await page.wait_for_load_state("networkidle", timeout=20000)
            await asyncio.sleep(random.uniform(1, 2))
        except Exception as e:
            logger.warning(f"SMILES page {origin}→{destination} {departure_date}: {e}")
            return []
        finally:
            await page.close()

        if not captured:
            logger.info(f"SMILES/{origin}→{destination} {departure_date}: sem resposta JSON capturada")
            return []

        return self._parse(captured[0], origin, destination, departure_date)

    def _parse(
        self, data: dict, origin: str, destination: str, departure_date: date
    ) -> List[Flight]:
        flights: List[Flight] = []
        try:
            segments = data.get("requestedFlightSegmentList", [])
            for segment in segments:
                for flight_data in segment.get("flightList", []):
                    stops = int(flight_data.get("stops", 0))
                    if stops > 1:
                        continue

                    dep_time = _parse_time(flight_data.get("departure", {}).get("date", ""))
                    arr_time = _parse_time(flight_data.get("arrival", {}).get("date", ""))

                    booking_url = (
                        f"{_SEARCH_BASE}"
                        f"?originAirportCode={origin}"
                        f"&destinationAirportCode={destination}"
                        f"&departureDate={departure_date.strftime('%d/%m/%Y')}"
                        f"&adults=1&tripType=2"
                    )

                    for avail in flight_data.get("availabilityList", []):
                        if int(avail.get("quantity", 0)) <= 0:
                            continue
                        miles = avail.get("fare", {}).get("miles")
                        if miles is None:
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
                            miles=int(miles),
                        ))
        except Exception as e:
            logger.error(f"SMILES parse error: {e}", exc_info=True)
        return flights
