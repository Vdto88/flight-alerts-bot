from datetime import date
from typing import List
from airlines.base import Flight, FlightSearcher

class AzulSearcher(FlightSearcher):
    AIRLINE_NAME = "AZUL"
    async def search(self, origin: str, destination: str, departure_date: date) -> List[Flight]:
        return []
