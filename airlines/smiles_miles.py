import asyncio
import calendar
import logging
import os
import random
from datetime import date, datetime, timedelta
from typing import List

from playwright.async_api import async_playwright, Browser
from playwright_stealth import Stealth

from airlines.base import Flight, FlightSearcher

logger = logging.getLogger(__name__)

# NOTE: Smiles uses a React MFE at /mfe/emissao-passagem. The MFE auto-triggers
# the flight search API (api-air-flightsearch-blue.smiles.com.br/v1/airlines/search)
# when loaded with correct URL params (originAirport, destinationAirport,
# departureDate as Unix ms timestamp, tripType=2).
#
# API requires x-api-key header (static, embedded in MFE JS bundle) and
# channel: WEB header. departureDate param is YYYY-MM-DD format.
#
# BLOCKED: Akamai Bot Manager returns HTTP 406 for all automated browsers.
# The _abck cookie value contains "-1" (bot detected) for all tools tested:
# playwright-stealth, nodriver, curl_cffi with Chrome TLS fingerprint.
# Akamai collects sensor data (mouse movements, timing, canvas fingerprint)
# and validates it server-side; headless environments fail this check.
#
# playwright-stealth patches navigator.webdriver and sec-ch-ua headers,
# improving the browser fingerprint, but Akamai's behavioral analysis still
# detects automation. _search_date() returns [] until this is resolved.
#
# To monitor: INFO log "SMILES ... HTTP 406" emitted on each blocked request.
_SEARCH_BASE = "https://www.smiles.com.br/passagens-aereas"
_MFE_BASE = "https://www.smiles.com.br/mfe/emissao-passagem"
_API_HOST = "api-air-flightsearch-blue.smiles.com.br"
_API_HOST_LEGACY = "flightavailability-prd.smiles.com.br"
_API_KEY = "aJqPU7xNHl9qN3NVZnPaJ208aPo2Bh2p2ZV844tw"


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
        async with Stealth().use_async(async_playwright()) as p:
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

        async with Stealth().use_async(async_playwright()) as p:
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
        page = await browser.new_page()
        captured: list = []
        blocked_406 = False

        async def handle_response(response):
            nonlocal blocked_406
            if _API_HOST not in response.url and _API_HOST_LEGACY not in response.url:
                return
            if response.status == 200:
                try:
                    data = await response.json()
                    captured.append(data)
                except Exception:
                    pass
            elif response.status == 406:
                blocked_406 = True
                logger.info(
                    f"SMILES/{origin}→{destination} {departure_date}: "
                    f"HTTP 406 (Akamai bloqueou) — retornando []"
                )

        page.on("response", handle_response)

        try:
            # MFE auto-triggers the search API when loaded with the correct params.
            # departureDate is a Unix millisecond timestamp.
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
            if not blocked_406:
                logger.info(
                    f"SMILES/{origin}→{destination} {departure_date}: sem resposta JSON capturada"
                )
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
