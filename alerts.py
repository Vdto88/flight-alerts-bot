import logging
from dataclasses import dataclass

from airlines.base import Flight

logger = logging.getLogger(__name__)


@dataclass
class AzulComparison:
    competitor: str          # cheapest non-Azul airline name, e.g. "LATAM"
    competitor_price: float  # BRL
    savings: float           # competitor_price - azul_price


@dataclass
class AzulAlert:
    flight: Flight           # the cheapest Azul flight on that date
    comparison: AzulComparison


def _is_azul(airline: str) -> bool:
    return "azul" in airline.lower()


def evaluate(flights: list[Flight]) -> list[AzulAlert]:
    """For one route's flights across dates, return Azul-cheapest alerts.

    Fires when, on a given departure date, the cheapest Azul fare is strictly
    lower than the cheapest competitor fare. Stops are not filtered. Requires
    at least one non-Azul competitor on the date.
    """
    by_date: dict = {}
    for f in flights:
        if f.price is None or f.price <= 0:
            continue
        by_date.setdefault(f.departure_date, []).append(f)

    alerts: list[AzulAlert] = []
    for _, day_flights in by_date.items():
        azul = [f for f in day_flights if _is_azul(f.airline)]
        others = [f for f in day_flights if not _is_azul(f.airline)]
        if not azul or not others:
            continue
        azul_best = min(azul, key=lambda f: f.price)
        other_best = min(others, key=lambda f: f.price)
        if azul_best.price < other_best.price:
            alerts.append(AzulAlert(
                flight=azul_best,
                comparison=AzulComparison(
                    competitor=other_best.airline,
                    competitor_price=other_best.price,
                    savings=round(other_best.price - azul_best.price, 2),
                ),
            ))
    return alerts
