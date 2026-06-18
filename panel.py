import json
from datetime import datetime, timezone

import alerts
from airlines.base import Flight
from config import PriceWatch


def build_deals(flights: list[Flight], region: str, watches: list[PriceWatch]) -> list[dict]:
    """For one route's flights, one record per date = the cheapest fare (any airline,
    price > 0). Signal flags reuse alerts.evaluate / evaluate_threshold as the single
    source of truth."""
    valid = [f for f in flights if f.price is not None and f.price > 0]
    by_date: dict = {}
    for f in valid:
        by_date.setdefault(f.departure_date, []).append(f)

    # azul_cheapest mirrors the "Azul mais barata" alert — True only when Azul beats at least
    # one NON-Azul competitor on that date. A date with only Azul flights is therefore False.
    azul_dates = {a.flight.departure_date for a in alerts.evaluate(flights)}
    watch_by_date = {
        t.flight.departure_date: t.max_price
        for t in alerts.evaluate_threshold(flights, watches)
    }

    deals: list[dict] = []
    for d, day_flights in by_date.items():
        cheapest = min(day_flights, key=lambda f: f.price)
        deals.append({
            "origem": cheapest.origin,
            "destino": cheapest.destination,
            "regiao": region,
            "cia": cheapest.airline,
            "data": d.isoformat(),
            "hora": cheapest.departure_time,
            "preco": cheapest.price,
            "paradas": cheapest.stops,
            "direto": cheapest.is_direct,
            "url_compra": cheapest.booking_url,
            "azul_cheapest": d in azul_dates,
            "price_watch": watch_by_date.get(d),
        })
    return deals


def write_deals(deals: list[dict], path: str, generated_at: datetime | None = None) -> str:
    ts = generated_at or datetime.now(timezone.utc)
    payload = {"gerado_em": ts.strftime("%Y-%m-%dT%H:%M:%SZ"), "deals": deals}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    return path
