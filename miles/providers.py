"""Read the same public offer feeds used by airline marketing pages.

No externally hosted daemon, proxy, login cookies, or booking inventory. Public feeds
are sparse: successful requests do not imply coverage of every flight/date.
"""
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from miles.model import Award
from miles.transport import Client
from scripts.azul_points_probe import collect, PAGE_URL

LATAM_API = "https://www.latamairlines.com/bff/web-engage-cms/v1/offers/dynamic/composite/multiple"
SMILES_HOME = "https://www.smiles.com.br/passagens"


def get(client, url, **kwargs):
    response = client.get(url, **kwargs)
    if response.status_code != 200:
        raise ValueError(f"HTTP {response.status_code}")
    return response


def parse_latam(payload):
    if not isinstance(payload.get("deals"), list):
        raise ValueError("LATAM offer format changed")
    awards = []
    for deal in payload["deals"]:
        price = deal.get("priceTrip") or {}
        points = price.get("totalLoyaltyAmount")
        if not points or deal.get("withoutOffer"):
            continue
        outbound, inbound = price.get("outboundDate"), price.get("inboundDate")
        if not outbound or deal.get("typeOfTrip") not in {"oneway", "roundtrip"}:
            continue
        if deal["typeOfTrip"] == "roundtrip" and not inbound:
            continue
        awards.append(Award(
            "latam", deal["originIataCode"], deal["destinationIataCode"],
            outbound, int(points), "https://www.latamairlines.com/br/pt",
            condition="Oferta pública LATAM Pass",
            cabin=(deal.get("cabinData") or {}).get("cabinCode") or "Não informada",
            return_date=inbound,
            # taxesPrice belongs to the cash fare in priceTrip. It is NOT a verified
            # award surcharge, so don't present it as the amount due for miles.
        ))
    return awards


def latam(plan):
    Client()  # Fail clearly when the mandatory local transport is missing.
    tasks = [(origin, destination, month) for (origin, destination), days in plan.items()
             for month in sorted({day[:7] for day in days})]

    def query(task):
        origin, destination, month = task
        headers = {"X-latam-Application-Country": "br", "X-latam-Application-Lang": "pt",
                   "X-latam-Application-Oc": "br", "X-latam-Client-Name": "web-engage-cms",
                   "X-latam-Application-Name": "web-engage-cms"}
        for name in ("App-Session-Id", "Track-Id", "Request-Id"):
            headers["X-latam-" + name] = str(uuid.uuid4())
        try:
            client = Client(timeout=12)
            data = get(client, LATAM_API, params={"pos": "BR", "country": "br",
                       "lt": "flights-to", "o": origin, "d": destination,
                       "miles": "true", "yearmonth": month}, headers=headers).json()
            return parse_latam(data), None
        except Exception as exc:
            return [], type(exc).__name__

    offers, failures = [], 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        for rows, error in pool.map(query, tasks):
            offers.extend(rows)
            failures += bool(error)
    return offers, {"requests": len(tasks), "failed_requests": failures,
                    "status": "error" if failures == len(tasks) else "partial" if failures else "ok"}


def azul(plan):
    Client()
    # One paginated origin feed includes every destination. Reverse routes have
    # their own origin feed, matching the existing two-direction alert config.
    offers, failures, incomplete = [], 0, False
    origins = sorted({origin for origin, _ in plan})
    for origin in origins:
        try:
            report = collect(origin, max_pages=20, client_factory=Client)
            incomplete |= not report["pagination_complete"]
            for row in report["offers"]:
                offers.append(Award("azul", row["origin"], row["destination"],
                    row["departure_date"], int(row["points"]), PAGE_URL,
                    cabin=row.get("travel_class") or "Não informada",
                    return_date=row.get("return_date"), condition="Oferta pública Azul Fidelidade"))
        except Exception:
            failures += 1
    return offers, {"requests": len(origins), "failed_requests": failures,
                    "status": "error" if failures == len(origins) else
                    "partial" if failures or incomplete else "ok"}


def parse_smiles(rows, source_url):
    if not isinstance(rows, list):
        raise ValueError("Smiles offer format changed")
    result = []
    for row in rows:
        # Smiles also advertises partners. This tab is specifically GOL.
        if str(row.get("Cia", "")).strip().upper() != "GOL":
            continue
        departure = datetime.strptime(row["data_saida"], "%d/%m/%Y").date().isoformat()
        for field, condition in (("Clube", "Clube Smiles ou Diamante"),
                                 ("Smiles", "Cliente Smiles")):
            raw = row.get(field)
            if raw is None or not re.fullmatch(r"\d+(?:\.\d{3})*", str(raw).strip()):
                continue
            # Published amount is per segment, even when the CTA preselects a
            # return. Never infer a round-trip total from the returnDate URL.
            result.append(Award("gol", row["iata_origem"], row["iata_destino"],
                                departure, int(str(raw).replace(".", "")),
                                source_url, condition=condition))
    return result


def gol(plan):
    with Client(timeout=15) as client:
        return _gol(client)


def _gol(client):
    home = get(client, SMILES_HOME).text
    soup = BeautifulSoup(home, "html.parser")
    all_campaigns = sorted({urljoin(SMILES_HOME, a["href"]) for a in soup.select('a[href]')
                        if urlparse(urljoin(SMILES_HOME, a["href"])).hostname == "www.smiles.com.br"
                        and "/aereas/" in a["href"]})
    campaigns = all_campaigns[:8]
    if not campaigns:
        raise ValueError("Smiles public campaigns not found")
    offers, failures, feeds, succeeded = [], 0, set(), 0
    for url in campaigns:
        try:
            html = get(client, url).text
            links = set(re.findall(r'["\'](/documents/[^"\'\s]+\.json/[^"\'\s]+)["\']', html))
            for link in sorted(links - feeds):
                feeds.add(link)
                offers.extend(parse_smiles(get(client, urljoin(url, link)).json(), url))
                succeeded += 1
        except Exception:
            failures += 1
    if not succeeded:
        raise ValueError("Smiles public offer feeds not found")
    return offers, {"requests": len(campaigns) + len(feeds), "failed_requests": failures,
                    "status": "partial" if failures or len(all_campaigns) > len(campaigns) else "ok"}
