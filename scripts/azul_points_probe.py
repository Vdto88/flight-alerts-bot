"""Read Azul's public, cached award offers; this is NOT live flight inventory.

Example: python scripts/azul_points_probe.py --origin CNF --destination CGH
No login, purchase, Telegram messages, or changes to the alert cycle.
"""

import argparse
import json
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

PAGE_URL = "https://passagens.voeazul.com.br/pt/buscador-de-pontos"
API_URL = "https://vg-api.airtrfx.com/graphql"
PAGE = {"tenant": "ad", "slug": "buscador-de-pontos", "siteEdition": "pt"}
QUERY = """
query GetStandardFareModule($page: PageInput!, $id: String!,
  $pageNumber: Int, $limit: Int, $filters: StandardFareModuleFiltersInput,
  $flatContext: FlatContextInput, $urlParameters: StandardFareModuleUrlParameters,
  $nearestOriginAirport: AirportInput) {
  standardFareModule(page: $page, id: $id, pageNumber: $pageNumber,
    limit: $limit, filters: $filters, flatContext: $flatContext,
    urlParameters: $urlParameters, nearestOriginAirport: $nearestOriginAirport) {
    error
    pagination { currentPage lastPage total }
    fares(pageNumber: $pageNumber, limit: $limit,
      urlParameters: $urlParameters, nearestOriginAirport: $nearestOriginAirport) {
      originAirportCode destinationAirportCode departureDate returnDate
      flightType travelClass departureTime returnTime stops
      priceLastSeen { value unit }
      redemption { unit amount taxAmount category }
    }
  }
}
"""
AIRPORT_QUERY = """
query GetStandardFareModuleAirports($page: PageInput!,
  $filters: StandardFareModuleAirportsFilterInput!) {
  standardFareModuleAirports(page: $page, filters: $filters) {
    airports { value geoId }
  }
}
"""


def graphql(client, headers, operation, query, variables):
    response = client.post(API_URL, headers=headers, json=[{
        "operationName": operation, "query": query, "variables": variables,
    }])
    response.raise_for_status()
    payload = response.json()
    item = payload[0] if isinstance(payload, list) else payload
    if item.get("errors"):
        raise ValueError("; ".join(e.get("message", "GraphQL error") for e in item["errors"]))
    return item["data"]


def airport_filter(client, headers, code, kind, origin=None):
    filters = {"language": "pt-br", "market": None, "getAirportType": kind}
    if origin:
        filters["selectedAirportCode"] = origin
    data = graphql(client, headers, "GetStandardFareModuleAirports", AIRPORT_QUERY,
                   {"page": PAGE, "filters": filters})
    match = next((a for a in data["standardFareModuleAirports"]["airports"]
                  if a["value"] == code), None)
    if match is None:
        raise ValueError(f"Airport {code} is not listed for this public search")
    return {"code": code, "geoId": match["geoId"]}


def airport(value):
    value = value.upper()
    if len(value) != 3 or not value.isascii() or not value.isalpha():
        raise argparse.ArgumentTypeError("Use a three-letter IATA code, e.g. CNF")
    return value


def collect(origin, destination=None, departure_date=None, max_pages=10, client_factory=httpx.Client):
    with client_factory(timeout=15, follow_redirects=True) as client:
        response = client.get(PAGE_URL)
        response.raise_for_status()
        script = BeautifulSoup(response.text, "html.parser").find(
            "script", id="__NEXT_DATA__"
        )
        if script is None:
            raise ValueError("Public Azul page has no expected page data")
        props = json.loads(script.string)["props"]["pageProps"]
        state = props["apolloState"]["data"]
        modules = [v for k, v in state.items() if k.startswith("StandardFareModule:")]
        if len(modules) != 1:
            raise ValueError("Public Azul page changed: expected one fare module")
        # Obtain the short-lived public-page token anew; never store or print it.
        headers = {
            "authorization": "Bearer " + props["jwt"],
            "origin": "https://passagens.voeazul.com.br",
            "referer": PAGE_URL,
        }
        variables = {
            "page": PAGE, "id": modules[0]["id"], "pageNumber": 1,
            "limit": 20,
            "filters": {"origin": airport_filter(client, headers, origin, "ORIGIN")},
            "flatContext": {"templateName": "Custom Page: Points HubPage"},
            "urlParameters": {}, "nearestOriginAirport": {},
        }
        if destination:
            variables["filters"]["destination"] = airport_filter(
                client, headers, destination, "DESTINATION", origin)
        offers, seen = [], set()
        last_page = None
        source_total = None
        pages_fetched = 0
        for page_number in range(1, max_pages + 1):
            variables["pageNumber"] = page_number
            module = graphql(client, headers, "GetStandardFareModule", QUERY,
                             variables)["standardFareModule"]
            if module.get("error"):
                raise ValueError(str(module["error"]))
            pagination = module["pagination"]
            last_page = pagination["lastPage"]
            source_total = pagination["total"]
            pages_fetched += 1
            for fare in module["fares"]:
                redemption = fare.get("redemption") or {}
                if redemption.get("unit") != "POINTS":
                    continue
                if fare["originAirportCode"] != origin:
                    continue
                if destination and fare["destinationAirportCode"] != destination:
                    continue
                if departure_date and fare["departureDate"] != departure_date:
                    continue
                points = redemption.get("amount")
                if points is None or points <= 0:
                    continue
                offer = {
                    "origin": fare["originAirportCode"],
                    "destination": fare["destinationAirportCode"],
                    "departure_date": fare["departureDate"],
                    "return_date": fare.get("returnDate") or None,
                    "journey_type": fare["flightType"],
                    "travel_class": fare["travelClass"],
                    "points": points, "taxes_brl": redemption.get("taxAmount"),
                    "departure_time": fare.get("departureTime"),
                    "stops": fare.get("stops"),
                    "price_last_seen": fare.get("priceLastSeen"),
                    "availability_confirmed": False,
                }
                key = json.dumps(offer, sort_keys=True)
                if key not in seen:
                    offers.append(offer)
                    seen.add(key)
            if page_number >= last_page:
                break
            time.sleep(0.5)
    offers.sort(key=lambda o: (o["points"], o["departure_date"], o["destination"]))
    return {
        "source": PAGE_URL,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "kind": "cached_advertised_award_offers",
        "notice": "Tariffs collected by Azul in the last 48 hours; availability and taxes require confirmation.",
        "origin": origin, "destination": destination,
        "departure_date_filter": departure_date,
        "pages_fetched": pages_fetched, "source_total": source_total,
        "pagination_complete": last_page is not None and pages_fetched >= last_page,
        "offers": offers,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", type=airport, default="CNF")
    parser.add_argument("--destination", type=airport)
    parser.add_argument("--date", type=date.fromisoformat)
    parser.add_argument("--max-pages", type=int, default=10)
    parser.add_argument("--output", type=Path, default=Path("data/azul-points-probe.json"))
    args = parser.parse_args()
    if not 1 <= args.max_pages <= 20:
        parser.error("--max-pages must be between 1 and 20")
    try:
        report = collect(args.origin, args.destination,
                         args.date.isoformat() if args.date else None, args.max_pages)
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        # Do not print response bodies, headers, or page tokens on failure.
        print(f"Azul probe failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{len(report['offers'])} cached offers; availability NOT confirmed")
    for offer in report["offers"][:15]:
        print(f"{offer['origin']} -> {offer['destination']} {offer['departure_date']} "
              f"{offer['points']:,.0f} points ({offer['journey_type']})")
    print(f"Pages: {report['pages_fetched']}; complete: {report['pagination_complete']}")
    print(f"Saved: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
