import asyncio
import logging
from datetime import date
from typing import List

import httpx

from config import REQUEST_TIMEOUT, REQUEST_RETRIES, REQUEST_RETRY_BACKOFF
from airlines.base import Flight, FlightSearcher

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.latamairlines.com/api/v1/flights"
_BOOKING_BASE = "https://www.latamairlines.com/br/pt/oferta-voos"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Accept": "application/json",
    "Referer": "https://www.latamairlines.com/",
}


class LatamSearcher(FlightSearcher):
    AIRLINE_NAME = "LATAM"

    async def search(self, origin: str, destination: str, departure_date: date) -> List[Flight]:
        params = {
            "origin": origin,
            "destination": destination,
            "outbound": departure_date.strftime("%Y-%m-%d"),
            "adults": 1,
            "cabin": "Economy",
            "redemption": "false",
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
                    return self._parse(response.json(), origin, destination, departure_date)
            except httpx.HTTPStatusError as e:
                logger.warning(
                    f"LATAM/{origin}→{destination} {departure_date}: HTTP {e.response.status_code}. "
                    "Se persistir 403, o endpoint pode ter mudado — verificar Network tab do browser."
                )
                return []
            except Exception as e:
                logger.warning(
                    f"LATAM/{origin}→{destination} {departure_date} tentativa {attempt + 1}/{REQUEST_RETRIES}: {e}"
                )
                if attempt < REQUEST_RETRIES - 1:
                    await asyncio.sleep(REQUEST_RETRY_BACKOFF)

        return []

    def _parse(self, data: dict, origin: str, destination: str, departure_date: date) -> List[Flight]:
        flights: List[Flight] = []
        try:
            # Support multiple common response shapes from LATAM's API
            itineraries = data.get("itineraries", data.get("flights", data.get("offers", [])))
            for it in itineraries:
                # Extract price — try multiple field names
                price_block = it.get("price", it.get("fare", it.get("totalAmount", {})))
                price = None
                if isinstance(price_block, dict):
                    raw = (
                        price_block.get("grandTotal")
                        or price_block.get("total")
                        or price_block.get("amount")
                    )
                    if raw is not None:
                        price = float(str(raw).replace(",", "."))
                elif isinstance(price_block, (int, float)):
                    price = float(price_block)

                if price is None:
                    continue

                segments = it.get("segments", it.get("legs", []))
                if not segments:
                    continue

                # stops = sum of numberOfStops per segment + number of connecting segments
                stops = sum(s.get("numberOfStops", 0) for s in segments) + max(0, len(segments) - 1)
                if stops > 1:
                    continue

                first_seg = segments[0]
                last_seg = segments[-1]

                dep_at = (
                    first_seg.get("departure", {}).get("at", "")
                    or first_seg.get("departureDateTime", "")
                )
                arr_at = (
                    last_seg.get("arrival", {}).get("at", "")
                    or last_seg.get("arrivalDateTime", "")
                )

                dep_time = dep_at[11:16].replace(":", "h") if len(dep_at) >= 16 else ""
                arr_time = arr_at[11:16].replace(":", "h") if len(arr_at) >= 16 else ""

                date_str = departure_date.strftime("%Y-%m-%d")
                booking_url = (
                    f"{_BOOKING_BASE}?origin={origin}&destination={destination}"
                    f"&outbound={date_str}&adults=1&cabin=Economy&redemption=false"
                )

                flights.append(Flight(
                    origin=origin,
                    destination=destination,
                    airline="LATAM",
                    departure_date=departure_date,
                    departure_time=dep_time,
                    arrival_time=arr_time,
                    price=price,
                    is_direct=(stops == 0),
                    stops=stops,
                    booking_url=booking_url,
                ))
        except Exception as e:
            logger.error(
                f"LATAM parse error: {e}. "
                f"Raw keys: {list(data.keys()) if isinstance(data, dict) else type(data)}"
            )
        return flights
