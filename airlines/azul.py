import asyncio
import logging
from datetime import date
from typing import List

import httpx
from bs4 import BeautifulSoup

from config import REQUEST_TIMEOUT, REQUEST_RETRIES, REQUEST_RETRY_BACKOFF
from airlines.base import Flight, FlightSearcher

logger = logging.getLogger(__name__)

_BASE_URL = "https://viagem.voeazul.com.br/travelShopping"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


class AzulSearcher(FlightSearcher):
    AIRLINE_NAME = "AZUL"

    async def search(self, origin: str, destination: str, departure_date: date) -> List[Flight]:
        params = {
            "from": origin,
            "to": destination,
            "depDate": departure_date.strftime("%d/%m/%Y"),
            "adults": 1,
            "infants": 0,
            "children": 0,
            "depFlex": 0,
            "currency": "BRL",
        }

        for attempt in range(REQUEST_RETRIES):
            try:
                async with httpx.AsyncClient(
                    timeout=REQUEST_TIMEOUT,
                    headers=_HEADERS,
                    follow_redirects=True,
                ) as client:
                    response = await client.get(_BASE_URL, params=params)
                    response.raise_for_status()

                    flights = self._parse(response.text, origin, destination, departure_date)
                    if not flights:
                        logger.warning(
                            f"AZUL/{origin}→{destination} {departure_date}: "
                            "página sem resultados parseáveis. "
                            "TODO: migrar para Playwright se o site renderizar apenas via JavaScript. "
                            "Ver: https://playwright.dev/python/"
                        )
                    return flights

            except httpx.HTTPStatusError as e:
                logger.warning(
                    f"AZUL/{origin}→{destination} {departure_date}: HTTP {e.response.status_code}"
                )
                return []
            except Exception as e:
                logger.warning(
                    f"AZUL/{origin}→{destination} {departure_date} tentativa {attempt + 1}/{REQUEST_RETRIES}: {e}"
                )
                if attempt < REQUEST_RETRIES - 1:
                    await asyncio.sleep(REQUEST_RETRY_BACKOFF)

        return []

    def _parse(self, html: str, origin: str, destination: str, departure_date: date) -> List[Flight]:
        flights: List[Flight] = []
        try:
            soup = BeautifulSoup(html, "lxml")

            # Azul's booking engine (VIAtravel) renders content via JavaScript.
            # These selectors target the static HTML that httpx can retrieve.
            # If the site moves to full client-side rendering, all selectors will miss.
            fare_cards = soup.select(
                ".fare-item, .flight-option, [class*='fare-card'], [class*='flight-result']"
            )
            if not fare_cards:
                return []

            for card in fare_cards:
                price_el = card.select_one(
                    "[class*='price'], [class*='valor'], [class*='fare-amount'], [class*='price-amount']"
                )
                if not price_el:
                    continue

                price_text = (
                    price_el.get_text(strip=True)
                    .replace("R$", "")
                    .replace("\xa0", "")
                    .replace(".", "")
                    .replace(",", ".")
                    .strip()
                )
                try:
                    price = float(price_text)
                except ValueError:
                    continue

                dep_el = card.select_one(
                    "[class*='departure'], [class*='hora-saida'], [class*='departure-time']"
                )
                arr_el = card.select_one(
                    "[class*='arrival'], [class*='hora-chegada'], [class*='arrival-time']"
                )
                stops_el = card.select_one(
                    "[class*='stop'], [class*='escala'], [class*='stops']"
                )

                dep_time = dep_el.get_text(strip=True).replace(":", "h") if dep_el else ""
                arr_time = arr_el.get_text(strip=True).replace(":", "h") if arr_el else ""

                stops = 0
                if stops_el:
                    stops_text = stops_el.get_text(strip=True).lower()
                    stops = 0 if "direto" in stops_text else 1

                date_str = departure_date.strftime("%d/%m/%Y")
                booking_url = (
                    f"{_BASE_URL}?from={origin}&to={destination}"
                    f"&depDate={date_str}&adults=1"
                )

                flights.append(Flight(
                    origin=origin,
                    destination=destination,
                    airline="AZUL",
                    departure_date=departure_date,
                    departure_time=dep_time,
                    arrival_time=arr_time,
                    price=price,
                    is_direct=(stops == 0),
                    stops=stops,
                    booking_url=booking_url,
                ))
        except Exception as e:
            logger.error(f"AZUL parse error: {e}")
        return flights
