import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import List, Optional
import asyncio
import logging

logger = logging.getLogger(__name__)


@dataclass
class Flight:
    origin: str           # IATA, e.g. "CNF"
    destination: str      # IATA, e.g. "IGU"
    airline: str          # "GOL" | "LATAM" | "AZUL" | "SMILES" | "AZUL_MILES"
    departure_date: date
    departure_time: str   # e.g. "07h40"
    arrival_time: str     # e.g. "09h10"
    price: float          # BRL — 0.0 para voos de milhas
    is_direct: bool
    stops: int            # 0 ou 1
    booking_url: str

    # Campos de milhas — None para voos em dinheiro
    miles: Optional[int] = None
    taxes_brl: Optional[float] = None  # reservado, sempre None por ora

    @property
    def is_miles_flight(self) -> bool:
        return self.miles is not None

    def cache_key(self, kind: str = "") -> str:
        prefix = f"{kind}|" if kind else ""
        if self.miles is not None:
            miles_floor = (self.miles // 1000) * 1000
            return f"{prefix}{self.airline}|{self.origin}|{self.destination}|{self.departure_date}|{miles_floor}mi"
        price_floor = math.floor(self.price / 10) * 10
        return f"{prefix}{self.airline}|{self.origin}|{self.destination}|{self.departure_date}|{price_floor}"


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

    async def search_dates(
        self, origin: str, destination: str, dates: List[date], batch_size: int = 7
    ) -> List[Flight]:
        """Search an explicit list of departure dates in concurrent batches."""
        all_flights: List[Flight] = []
        for start in range(0, len(dates), batch_size):
            batch = dates[start:start + batch_size]
            tasks = [self.search(origin, destination, d) for d in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, list):
                    all_flights.extend(result)
                else:
                    logger.warning(f"{self.AIRLINE_NAME} search_dates error: {result}")
        return all_flights
