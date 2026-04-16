import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, timedelta
from typing import List
import asyncio
import logging

logger = logging.getLogger(__name__)


@dataclass
class Flight:
    origin: str           # IATA, e.g. "CNF"
    destination: str      # IATA, e.g. "GRU"
    airline: str          # "GOL" | "LATAM" | "AZUL"
    departure_date: date
    departure_time: str   # e.g. "07h40"
    arrival_time: str     # e.g. "09h10"
    price: float          # BRL
    is_direct: bool
    stops: int            # 0 or 1
    booking_url: str

    def cache_key(self) -> str:
        price_floor = math.floor(self.price / 10) * 10
        return f"{self.airline}|{self.origin}|{self.destination}|{self.departure_date}|{price_floor}"


class FlightSearcher(ABC):
    AIRLINE_NAME: str = ""

    @abstractmethod
    async def search(self, origin: str, destination: str, departure_date: date) -> List[Flight]:
        """Search flights for a single departure date. Returns [] on any error."""

    async def search_range(self, origin: str, destination: str, days_ahead: int = 60, batch_size: int = 7) -> List[Flight]:
        """Search the next `days_ahead` days in batches of `batch_size` dates."""
        today = date.today()
        dates = [today + timedelta(days=i) for i in range(1, days_ahead + 1)]
        all_flights: List[Flight] = []

        for batch_start in range(0, len(dates), batch_size):
            batch = dates[batch_start:batch_start + batch_size]
            tasks = [self.search(origin, destination, d) for d in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, list):
                    all_flights.extend(result)
                else:
                    logger.warning(f"{self.AIRLINE_NAME} batch error: {result}")

        return all_flights
