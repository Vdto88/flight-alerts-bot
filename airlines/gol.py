import asyncio
import logging
from datetime import date
from typing import List

import httpx

from config import GOL_API_KEY, REQUEST_TIMEOUT, REQUEST_RETRIES, REQUEST_RETRY_BACKOFF
from airlines.base import Flight, FlightSearcher

logger = logging.getLogger(__name__)

_BASE_URL = "https://api-air-flightsearch-prd.smiles.com.br/v1/airlines/search"
_BOOKING_BASE = "https://www.smiles.com.br/passagem-de-aviao/compre-com-dinheiro"


class GolSearcher(FlightSearcher):
    AIRLINE_NAME = "GOL"

    async def search(self, origin: str, destination: str, departure_date: date) -> List[Flight]:
        params = {
            "departureDate": departure_date.strftime("%Y-%m-%d"),
            "originAirportCode": origin,
            "destinationAirportCode": destination,
            "adults": 1,
            "cabinType": "economic",
            "currencyCode": "BRL",
        }
        headers = {
            "api-key": GOL_API_KEY,
            "x-api-key": GOL_API_KEY,
            "region": "BRAZIL",
        }

        for attempt in range(REQUEST_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                    response = await client.get(_BASE_URL, params=params, headers=headers)
                    response.raise_for_status()
                    return self._parse(response.json(), origin, destination)
            except httpx.HTTPStatusError as e:
                logger.warning(
                    f"GOL/{origin}→{destination} {departure_date}: HTTP {e.response.status_code}"
                )
                return []
            except Exception as e:
                logger.warning(
                    f"GOL/{origin}→{destination} {departure_date} tentativa {attempt + 1}/{REQUEST_RETRIES}: {e}"
                )
                if attempt < REQUEST_RETRIES - 1:
                    await asyncio.sleep(REQUEST_RETRY_BACKOFF)

        return []

    def _parse(self, data: dict, origin: str, destination: str) -> List[Flight]:
        flights: List[Flight] = []
        try:
            for segment in data.get("requestedFlightSegmentList", []):
                for f in segment.get("flightList", []):
                    if not f.get("available", True):
                        continue
                    stops = f.get("stops", 0)
                    if stops > 1:
                        continue

                    fare_list = f.get("fareList", [])
                    if not fare_list:
                        continue

                    price = None
                    for fare in fare_list:
                        money = fare.get("money", {})
                        amount = money.get("totalFare") or money.get("originalAmount")
                        if amount is not None:
                            val = float(amount)
                            if price is None or val < price:
                                price = val
                    if price is None:
                        continue

                    dep = f.get("departure", {})
                    arr = f.get("arrival", {})
                    dep_date_str = dep.get("date", "")
                    try:
                        dep_date = date.fromisoformat(dep_date_str)
                    except (ValueError, TypeError):
                        continue

                    dep_time = dep.get("hour", "").replace(":", "h")
                    arr_time = arr.get("hour", "").replace(":", "h")
                    booking_url = (
                        f"{_BOOKING_BASE}?originAirportCode={origin}"
                        f"&destinationAirportCode={destination}"
                        f"&departureDate={dep_date_str}&adults=1&cabinType=economic"
                    )

                    flights.append(Flight(
                        origin=origin,
                        destination=destination,
                        airline="GOL",
                        departure_date=dep_date,
                        departure_time=dep_time,
                        arrival_time=arr_time,
                        price=price,
                        is_direct=(stops == 0),
                        stops=stops,
                        booking_url=booking_url,
                    ))
        except Exception as e:
            logger.error(f"GOL parse error: {e}. Raw keys: {list(data.keys()) if isinstance(data, dict) else type(data)}")
        return flights
