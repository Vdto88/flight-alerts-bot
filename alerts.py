import logging
import math
from dataclasses import dataclass
from datetime import timedelta

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


from config import PriceWatch


@dataclass
class ThresholdAlert:
    flight: Flight        # the cheapest fare on that date (any airline)
    max_price: float      # the watch limit it satisfied


def evaluate_threshold(flights: list[Flight], watches: list[PriceWatch]) -> list[ThresholdAlert]:
    """For one route's flights, return price alerts where the cheapest fare on a date inside
    a watch's window is <= that watch's max_price. Airline-agnostic; ignores price <= 0.
    Emits at most one alert per date (the tightest satisfied limit)."""
    if not watches:
        return []

    by_date: dict = {}
    for f in flights:
        if f.price is None or f.price <= 0:
            continue
        by_date.setdefault(f.departure_date, []).append(f)

    alerts: list[ThresholdAlert] = []
    for d, day_flights in by_date.items():
        cheapest = min(day_flights, key=lambda f: f.price)
        matching = [
            w for w in watches
            if (w.window is None or w.window.start <= d <= w.window.end)
            and cheapest.price <= w.max_price
        ]
        if matching:
            best = min(matching, key=lambda w: w.max_price)
            alerts.append(ThresholdAlert(flight=cheapest, max_price=best.max_price))
    return alerts


from config import RoundTripWatch


@dataclass
class RoundTripAlert:
    watch_name: str
    ida: Flight
    volta: Flight
    stay_days: int
    total: float
    max_total: float


def _cheapest_by_date(legs: list[Flight], lo=None, hi=None) -> dict:
    """Map departure_date -> cheapest Flight on that date (price > 0), optionally
    restricted to [lo, hi]."""
    out: dict = {}
    for f in legs:
        if f.price is None or f.price <= 0:
            continue
        d = f.departure_date
        if (lo is not None and d < lo) or (hi is not None and d > hi):
            continue
        if d not in out or f.price < out[d].price:
            out[d] = f
    return out


def evaluate_round_trip(ida_legs: list[Flight], volta_legs: list[Flight],
                        watch: RoundTripWatch) -> list[RoundTripAlert]:
    """One alert per ida departure date inside watch.depart_window whose cheapest
    open-jaw round-trip (cheapest ida that day + cheapest volta stay_min..stay_max
    days later) totals <= watch.max_total."""
    w = watch
    ida_by_date = _cheapest_by_date(ida_legs, w.depart_window.start, w.depart_window.end)
    volta_by_date = _cheapest_by_date(volta_legs)

    alerts: list[RoundTripAlert] = []
    for d in sorted(ida_by_date):
        best = None  # (total, volta_flight, stay_days)
        for s in range(w.stay_min, w.stay_max + 1):
            volta = volta_by_date.get(d + timedelta(days=s))
            if volta is None:
                continue
            total = ida_by_date[d].price + volta.price
            if best is None or total < best[0]:
                best = (total, volta, s)
        if best is None or best[0] > w.max_total:
            continue
        total, volta, s = best
        alerts.append(RoundTripAlert(
            watch_name=w.name, ida=ida_by_date[d], volta=volta,
            stay_days=s, total=round(total, 2), max_total=w.max_total,
        ))
    return alerts


def round_trip_cache_key(rt: RoundTripAlert) -> str:
    total_floor = math.floor(rt.total / 10) * 10
    return (f"rt:{rt.watch_name}|{rt.ida.origin}-{rt.ida.destination}|{rt.ida.departure_date}"
            f"|{rt.volta.origin}-{rt.volta.destination}|{rt.volta.departure_date}|{total_floor}")
