import asyncio
import logging
import re
from datetime import date
from functools import partial
from typing import List, Optional

from fast_flights import FlightData, Passengers, get_flights

from airlines.base import Flight, FlightSearcher

logger = logging.getLogger(__name__)

_BOOKING_BASE = "https://www.google.com/travel/flights"


def _parse_time(raw: str) -> str:
    """Convert '7:40 AM' / '3:05 PM' to '07h40' / '15h05'."""
    if not raw:
        return ""
    m = re.match(r"(\d{1,2}):(\d{2})\s*(AM|PM)", raw.strip(), re.IGNORECASE)
    if not m:
        return ""
    hour, minute, period = int(m.group(1)), int(m.group(2)), m.group(3).upper()
    if period == "PM" and hour != 12:
        hour += 12
    elif period == "AM" and hour == 12:
        hour = 0
    return f"{hour:02d}h{minute:02d}"


def _parse_price(raw: str) -> Optional[float]:
    """Extract float from strings like 'R$289', 'R$ 1.290,50', 'R$1.290', '$289'."""
    if not raw:
        return None
    cleaned = re.sub(r"[^\d,.]", "", raw.strip())
    if not cleaned:
        return None
    # Dot-as-thousands-separator: "1.290" or "1.290.000" with no comma
    if re.search(r"\.\d{3}$", cleaned) and "," not in cleaned:
        cleaned = cleaned.replace(".", "")
    elif re.search(r",\d{2}$", cleaned):
        # European decimal format: 1.290,50
        cleaned = cleaned.replace(".", "").replace(",", ".")
    else:
        # US format: 1,290.50 or 1,290
        cleaned = cleaned.replace(",", "")
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


class GoogleFlightsSearcher(FlightSearcher):
    AIRLINE_NAME = "GOOGLE_FALLBACK"

    async def search(self, origin: str, destination: str, departure_date: date) -> List[Flight]:
        date_str = departure_date.strftime("%Y-%m-%d")
        fn = partial(
            get_flights,
            flight_data=[FlightData(date=date_str, from_airport=origin, to_airport=destination)],
            passengers=Passengers(adults=1),
            trip="one-way",
            seat="economy",
        )
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(None, fn)
        except Exception as e:
            logger.warning(f"Google Flights/{origin}→{destination} {departure_date}: {e}")
            return []

        return self._parse(result, origin, destination, departure_date)

    def _parse(self, result, origin: str, destination: str, departure_date: date) -> List[Flight]:
        flights: List[Flight] = []
        try:
            for ff in result.flights:
                price = _parse_price(ff.price or "")
                if price is None:
                    continue
                stops = int(ff.stops) if ff.stops is not None else 0
                if stops > 1:
                    continue
                dep_time = _parse_time(ff.departure or "")
                arr_time = _parse_time(ff.arrival or "")
                booking_url = (
                    f"{_BOOKING_BASE}/search?hl=pt-BR"
                    f"&q=flights+from+{origin}+to+{destination}"
                    f"+on+{departure_date.strftime('%Y-%m-%d')}"
                )
                flights.append(Flight(
                    origin=origin,
                    destination=destination,
                    airline=ff.name or "GOOGLE_FALLBACK",
                    departure_date=departure_date,
                    departure_time=dep_time,
                    arrival_time=arr_time,
                    price=price,
                    is_direct=(stops == 0),
                    stops=stops,
                    booking_url=booking_url,
                ))
        except Exception as e:
            logger.error(f"Google Flights parse error: {e}")
        return flights
