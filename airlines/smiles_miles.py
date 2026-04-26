import asyncio
import calendar
import logging
import os
import random
from datetime import date, datetime, timedelta
from typing import List

from playwright.async_api import async_playwright, Browser

from airlines.base import Flight, FlightSearcher

logger = logging.getLogger(__name__)

# NOTE: Smiles migrated from /passagens-aereas (Liferay portlet) to a React MFE
# at /mfe/emissao-passagem. The new search API is api-air-flightsearch-blue.smiles.com.br.
# The MFE page auto-triggers the flight search when loaded with correct URL params
# (tripType, originAirport, destinationAirport, departureDate as Unix ms timestamp).
#
# BLOCKED: Akamai Bot Manager (bm_ss/bm_s/bm_sz/_abck cookies) returns HTTP 406
# for all headless Playwright requests to api-air-flightsearch-blue, detected via
# sec-ch-ua: "HeadlessChrome". Launching with channel="chrome" does not bypass it.
# Form selectors for /passagens-aereas (legacy fallback, also blocked for search):
#   origin: #inputOrigin, destination: #inputDestination,
#   date: #_smilesflightsearchportlet_WAR_smilesbookingportlet_departure_date,
#   submit: #submitFlightSearch (hidden until #inputOrigin is clicked to expand form)
#
# _search_date() currently returns [] for all requests due to this block.
_SEARCH_BASE = "https://www.smiles.com.br/passagens-aereas"
_MFE_BASE = "https://www.smiles.com.br/mfe/emissao-passagem"
_API_HOST = "api-air-flightsearch-blue.smiles.com.br"
_API_HOST_LEGACY = "flightavailability-prd.smiles.com.br"


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
                    try:
                        flights = await self._search_date(browser, origin, destination, d)
                        all_flights.extend(flights)
                        await asyncio.sleep(random.uniform(2, 4))
                    except Exception as e:
                        logger.warning(f"SMILES/{origin}→{destination} {d}: erro inesperado: {e}")
                        continue
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
            if (
                (_API_HOST in response.url or _API_HOST_LEGACY in response.url)
                and response.status == 200
            ):
                try:
                    data = await response.json()
                    captured.append(data)
                except Exception:
                    pass

        page.on("response", handle_response)

        try:
            # MFE page auto-triggers the search API when loaded with timestamp param
            departure_ts = int(
                calendar.timegm(
                    datetime(departure_date.year, departure_date.month, departure_date.day).timetuple()
                )
            ) * 1000
            url = (
                f"{_MFE_BASE}"
                f"?tripType=2"
                f"&originAirport={origin}"
                f"&destinationAirport={destination}"
                f"&departureDate={departure_ts}"
                f"&adults=1&children=0&infants=0"
                f"&cabinType=all&isFlexibleDateChecked=false"
            )
            await page.goto(url, timeout=30000, wait_until="domcontentloaded")
            await asyncio.sleep(random.uniform(8, 12))
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
