import asyncio
import logging
import re
from datetime import date
from functools import partial
from typing import List, Optional

from fast_flights import FlightData, Passengers
# get_flights() does not expose the currency; call the engine directly so we can
# pin BRL. Without this, prices follow the runner's IP (USD from GitHub's US IP).
from fast_flights.core import get_flights_from_filter
from fast_flights.filter import TFSData

from airlines.base import Flight, FlightSearcher

logger = logging.getLogger(__name__)

_BOOKING_BASE = "https://www.google.com/travel/flights"
_CURRENCY = "BRL"
# Google lists some fares (self-transfer itineraries) with no carrier name.
NO_AIRLINE_LABEL = "Cia não informada"

MAX_RETRIES = 2          # extra attempts after the first
RETRY_BACKOFF_S = 1.0    # sleep is RETRY_BACKOFF_S * attempt: 1 s, then 2 s
_NO_FLIGHTS = "No flights found"


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


def _parse_stops(raw) -> int:
    """fast_flights returns stops as an int, or 'Unknown' when it can't tell.
    Treat non-numeric/None as 1 (connecting). Stops are not filtered — only shown."""
    try:
        return int(raw)
    except (ValueError, TypeError):
        return 1


class GoogleFlightsSearcher(FlightSearcher):
    AIRLINE_NAME = "GOOGLE_FALLBACK"

    def __init__(self) -> None:
        self.queries = 0
        self.failures = 0
        self.no_flights = 0

    def reset_counters(self) -> None:
        self.queries = 0
        self.failures = 0
        self.no_flights = 0

    async def _search_once(self, origin: str, destination: str,
                           departure_date: date) -> Optional[List[Flight]]:
        """One fetch + parse, with no sleeping and no counting of queries/failures.
        `None` means a transient failure worth retrying; `[]` is a valid empty answer."""
        date_str = departure_date.strftime("%Y-%m-%d")
        tfs = TFSData.from_interface(
            flight_data=[FlightData(date=date_str, from_airport=origin, to_airport=destination)],
            trip="one-way",
            passengers=Passengers(adults=1),
            seat="economy",
            max_stops=None,
        )
        fn = partial(get_flights_from_filter, tfs, currency=_CURRENCY, mode="common")
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(None, fn)
        except Exception as e:
            # fast_flights raises when a date simply has no fares and puts the whole page in
            # the message: a valid empty answer, not worth a retry or 5 KB of log. Matched
            # anywhere in the message so a changed prefix upstream still hits; the counter
            # next door is what makes a broken match visible (it drops to zero).
            if _NO_FLIGHTS in str(e):
                self.no_flights += 1
                logger.debug(f"Google Flights/{origin}→{destination} {departure_date}: sem voos")
                return []
            logger.debug(f"Google Flights/{origin}→{destination} {departure_date}: "
                         f"tentativa falhou: {str(e)[:160]}")
            return None
        return self._parse(result, origin, destination, departure_date)

    async def search(self, origin: str, destination: str, departure_date: date) -> List[Flight]:
        """Single date, retried inline with backoff. `search_dates` below retries at the end
        of the route instead; this path stays for one-off lookups."""
        self.queries += 1
        for attempt in range(MAX_RETRIES + 1):
            flights = await self._search_once(origin, destination, departure_date)
            if flights is not None:
                return flights
            if attempt == MAX_RETRIES:
                self.failures += 1
                logger.warning(
                    f"Google Flights/{origin}→{destination} {departure_date}: "
                    f"falhou após {MAX_RETRIES + 1} tentativas (motivo no log DEBUG)"
                )
                return []
            await asyncio.sleep(RETRY_BACKOFF_S * (attempt + 1))
        return []

    async def search_dates(
        self, origin: str, destination: str, dates: List[date], batch_size: int = 7
    ) -> List[Flight]:
        """Search a route's dates in concurrent batches, then retry the dates that failed in
        further passes at the END of the route. Retrying inside a batch would make every batch
        wait for its slowest member's backoff; here each pass pays a single sleep for the whole
        route, whatever number of dates it is re-running."""
        all_flights: List[Flight] = []
        self.queries += len(dates)
        pending = list(dates)
        for attempt in range(MAX_RETRIES + 1):
            if not pending:
                break
            if attempt:
                await asyncio.sleep(RETRY_BACKOFF_S * attempt)
            failed: List[date] = []
            for start in range(0, len(pending), batch_size):
                batch = pending[start:start + batch_size]
                results = await asyncio.gather(
                    *(self._search_once(origin, destination, d) for d in batch),
                    return_exceptions=True,
                )
                for d, result in zip(batch, results):
                    if isinstance(result, list):
                        all_flights.extend(result)
                        continue
                    if isinstance(result, BaseException):
                        logger.debug(f"Google Flights/{origin}→{destination} {d}: "
                                     f"tentativa falhou: {str(result)[:160]}")
                    failed.append(d)
            pending = failed

        if pending:
            self.failures += len(pending)
            logger.warning(
                f"Google Flights/{origin}→{destination}: {len(pending)} data(s) falharam "
                f"após {MAX_RETRIES + 1} tentativas"
            )
        return all_flights

    def _parse(self, result, origin: str, destination: str, departure_date: date) -> List[Flight]:
        flights: List[Flight] = []
        try:
            for ff in result.flights:
                price = _parse_price(ff.price or "")
                if price is None:
                    continue
                stops = _parse_stops(ff.stops)
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
                    airline=ff.name or NO_AIRLINE_LABEL,
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
