import json
from dataclasses import asdict, dataclass
from datetime import date
from math import isfinite


@dataclass(frozen=True)
class Award:
    airline: str
    origin: str
    destination: str
    departure_date: str
    points: int
    url: str
    condition: str = "Condição não informada"
    cabin: str = "Não informada"
    return_date: str | None = None
    taxes_brl: float | None = None
    date_end: str | None = None

    def __post_init__(self):
        date.fromisoformat(self.departure_date)
        for value in (self.return_date, self.date_end):
            if value and date.fromisoformat(value) < date.fromisoformat(self.departure_date):
                raise ValueError("Invalid date range")
        if self.airline not in {"azul", "latam", "gol"} or self.origin == self.destination:
            raise ValueError("Invalid airline or route")
        if isinstance(self.points, bool) or self.points <= 0 or not isfinite(self.points):
            raise ValueError("Invalid award amount")

    @property
    def key(self):
        # Membership, cabin and journey must match before comparing two prices.
        return json.dumps([self.airline, self.origin, self.destination,
                           self.departure_date, self.return_date, self.date_end,
                           self.condition, self.cabin], separators=(",", ":"))

    def payload(self):
        return {**asdict(self), "availability_confirmed": False,
                "journey_type": "roundtrip" if self.return_date else "oneway"}
