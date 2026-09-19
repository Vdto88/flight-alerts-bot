import json
from datetime import datetime, timezone

import alerts
import history
from airlines.base import Flight
from alerts import RoundTripAlert
from config import AIRPORTS, AZUL_HUB, PriceWatch


def place_fields(airport: str) -> dict:
    """City / state / country of an airport, for the panel. An airport missing from
    config.AIRPORTS degrades to its own code instead of breaking the snapshot."""
    a = AIRPORTS.get(airport)
    if a is None:
        return {"cidade": airport, "uf": None, "pais": ""}
    return {"cidade": a.cidade, "uf": a.uf, "pais": a.pais}


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
            **place_fields(
                cheapest.destination if cheapest.origin == AZUL_HUB else cheapest.origin
            ),
        })
    return deals


def write_deals(deals: list[dict], path: str, generated_at: datetime | None = None) -> str:
    ts = generated_at or datetime.now(timezone.utc)
    payload = {
        "gerado_em": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "aeroportos": {code: place_fields(code) for code in AIRPORTS},
        "deals": deals,
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    return path


def build_round_trip_deals(rt_alerts: list[RoundTripAlert], region: str) -> list[dict]:
    """One panel record per round-trip alert. `tipo:"roundtrip"` carries both legs;
    origem/destino/data/preco/url_compra mirror the ida leg (with preco = total) so the
    existing filters and sorting keep working."""
    deals: list[dict] = []
    for rt in rt_alerts:
        deals.append({
            "tipo": "roundtrip",
            "regiao": region,
            "origem": rt.ida.origin,
            "destino": rt.ida.destination,
            "data": rt.ida.departure_date.isoformat(),
            "cia": rt.ida.airline,
            "preco": rt.total,
            "paradas": rt.ida.stops,
            "direto": rt.ida.is_direct,
            "url_compra": rt.ida.booking_url,
            "azul_cheapest": False,
            "price_watch": None,
            "ida_origem": rt.ida.origin,
            "ida_destino": rt.ida.destination,
            "data_ida": rt.ida.departure_date.isoformat(),
            "cia_ida": rt.ida.airline,
            "preco_ida": rt.ida.price,
            "url_ida": rt.ida.booking_url,
            "volta_origem": rt.volta.origin,
            "volta_destino": rt.volta.destination,
            "data_volta": rt.volta.departure_date.isoformat(),
            "cia_volta": rt.volta.airline,
            "preco_volta": rt.volta.price,
            "url_volta": rt.volta.booking_url,
            "estadia": rt.stay_days,
            "max_total": rt.max_total,
            **place_fields(rt.ida.destination),
        })
    return deals


def enrich_with_history(deals: list[dict], stats: dict[str, dict]) -> int:
    """Attach the price history of each deal's route+date: window low, median, sparkline,
    and how far today's fare sits from that median. Deals with fewer than two days of
    observations are left alone — one point says nothing about cheap or expensive.
    Round-trip records are skipped: their `preco` is a two-leg total, not comparable to
    the one-way history stored under the same key."""
    enriched = 0
    for deal in deals:
        if deal.get("tipo") == "roundtrip":
            continue
        entry = stats.get(history.deal_key(deal))
        if entry is None or len(entry["spark"]) < 2:
            continue
        deal["hist_min"] = entry["min"]
        deal["hist_med"] = entry["med"]
        deal["spark"] = entry["spark"]
        deal["delta_pct"] = round((deal["preco"] - entry["med"]) / entry["med"] * 100)
        deal["menor_hist"] = deal["preco"] <= entry["min"]
        enriched += 1
    return enriched
