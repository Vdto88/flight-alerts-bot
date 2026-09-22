import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import alerts
import history
from airlines.base import Flight
from alerts import RoundTripAlert
from config import (AIRPORTS, AZUL_HUB, PriceWatch, STAY_OPTIONS, STAY_OPTIONS_DEFAULT,
                    WINDOW_MAX_DAYS)

logger = logging.getLogger(__name__)


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
        # The panels print this window next to every delta; hard-coding it there went stale once.
        "hist_janela_dias": history.STATS_DAYS,
        # The near band, for the panel's "atualizadas uma vez por dia" note on far dates.
        "janela_perto_dias": WINDOW_MAX_DAYS,
        "aeroportos": {code: place_fields(code) for code in AIRPORTS},
        # Stays the new panel's round-trip selector offers, per country of the destination.
        "estadias": {"por_pais": {k: list(v) for k, v in STAY_OPTIONS.items()},
                     "padrao": list(STAY_OPTIONS_DEFAULT)},
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


def enrich_with_history(deals: list[dict], stats: dict[str, dict],
                        route_stats: dict[str, dict] | None = None) -> int:
    """Attach history to each one-way deal: its own route+date series (low, median,
    sparkline, gap to the median) when there are two or more days of observations, and
    the route-level median and floor whenever the route has enough flight dates — so a
    date never seen before still gets a verdict. Round-trip records are skipped: their
    `preco` is a two-leg total. Returns how many deals got a date-level series."""
    route_stats = route_stats or {}
    enriched = 0
    for deal in deals:
        if deal.get("tipo") == "roundtrip":
            continue
        route = route_stats.get(f"{deal['origem']}|{deal['destino']}")
        if route and route["n_dates"] >= history.MIN_ROUTE_DATES:
            deal["rota_med"] = route["med"]
            deal["rota_min"] = route["min"]
            deal["rota_delta_pct"] = round((deal["preco"] - route["med"]) / route["med"] * 100)

        entry = stats.get(history.deal_key(deal))
        if entry is None or len(entry["spark"]) < 2:
            continue
        deal["hist_min"] = entry["min"]
        deal["hist_med"] = entry["med"]
        deal["spark"] = entry["spark"]
        deal["delta_pct"] = round((deal["preco"] - entry["med"]) / entry["med"] * 100)
        deal["menor_hist"] = deal["preco"] <= entry["min"]
        if "n" in entry:
            deal["hist_dias"] = entry["n"]
            deal["hist_desde"] = entry["since"]
        enriched += 1
    return enriched


def build_history_payload(route_stats: dict[str, dict], series: dict[str, list[list]],
                          generated_at: datetime | None = None) -> dict:
    """What the panel downloads lazily to draw charts: per-route summary plus the daily
    series of every live route+date."""
    ts = generated_at or datetime.now(timezone.utc)
    return {"gerado_em": ts.strftime("%Y-%m-%dT%H:%M:%SZ"), "rotas": route_stats, "series": series}


def write_history_files(payload: dict, out_dir: str) -> int:
    """Split the history payload into one file per route, `<ORIG>-<DEST>.json`, so the panel
    downloads only the route whose pass is open. Files left from a previous cycle (plain or
    encrypted) are removed first so dropped routes do not linger. Returns the files written.

    The payload is parsed BEFORE anything is deleted: a Pages deploy is a full replacement, so
    throwing halfway would publish an empty history/ and cost every route its charts. One bad
    key costs its own series, exactly as history._split_key does for the database."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    by_route: dict[str, dict] = {}
    skipped = 0
    for key, points in payload["series"].items():
        parts = key.split("|")
        if len(parts) != 3:
            skipped += 1
            continue
        by_route.setdefault(f"{parts[0]}|{parts[1]}", {})[key] = points
    if skipped:
        logger.warning(f"histórico do painel: {skipped} chave(s) inválida(s) ignorada(s)")
    if payload["series"] and not by_route:
        logger.error("histórico do painel: nenhuma chave utilizável; "
                     "os arquivos do ciclo anterior foram mantidos")
        return 0

    for old in out.glob("*.json"):          # matches *.enc.json too
        old.unlink()
    for route, series in by_route.items():
        body = {"gerado_em": payload["gerado_em"], "rota": payload["rotas"].get(route), "series": series}
        with open(out / f"{route.replace('|', '-')}.json", "w", encoding="utf-8") as fh:
            json.dump(body, fh, ensure_ascii=False)
    return len(by_route)
