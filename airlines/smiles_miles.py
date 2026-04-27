import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import List

from airlines.base import Flight, FlightSearcher

logger = logging.getLogger(__name__)

# NOTE: Smiles API is protected by Akamai Bot Manager (HTTP 406 for automation).
# Automated browsers get _abck cookie with "-1" (bot detected), even with
# playwright-stealth, nodriver, and curl_cffi Chrome TLS fingerprinting.
#
# Working approach: scripts/harvest_cookies.py launches real Chrome (no automation
# flags), user does a warm-up browse to validate the Akamai session, then the
# script uses playwright CDP to drive that same Chrome and capture API responses.
# Results are cached in scripts/smiles_cache.json for ~2h.
#
# SmilesMilesSearcher reads exclusively from this cache.
# Run scripts/harvest_cookies.py to refresh the cache.
_SEARCH_BASE = "https://www.smiles.com.br/passagens-aereas"
_API_HOST = "api-air-flightsearch-blue.smiles.com.br"
_CACHE_FILE = Path(__file__).parent.parent / "scripts" / "smiles_cache.json"
_CACHE_MAX_AGE_SECONDS = 7200  # 2h


def _load_results_cache(origin: str, destination: str, departure_date: date) -> list | None:
    """
    Returns cached flights for this route/date, or None if cache is absent/expired.
    Cache is populated by scripts/harvest_cookies.py.
    """
    if not _CACHE_FILE.exists():
        return None
    try:
        payload = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        harvested_at = datetime.fromisoformat(payload["harvested_at"])
        age = (datetime.now(timezone.utc) - harvested_at).total_seconds()
        if age > _CACHE_MAX_AGE_SECONDS:
            return None
        key = f"{origin}-{destination}-{departure_date}"
        entries = payload.get("flights", {}).get(key)
        if entries is None:
            return None
        return [
            Flight(
                origin=e["origin"],
                destination=e["destination"],
                airline="SMILES",
                departure_date=departure_date,
                departure_time=e["departure_time"],
                arrival_time=e["arrival_time"],
                price=0.0,
                is_direct=e["is_direct"],
                stops=e["stops"],
                booking_url=e["booking_url"],
                miles=e["miles"],
            )
            for e in entries
        ]
    except Exception as e:
        logger.warning(f"SMILES: erro ao ler cache: {e}")
        return None


def _parse_time(iso_str: str) -> str:
    """Extracts 'HHhMM' from '2026-07-15T07:40:00'."""
    if not iso_str or "T" not in iso_str:
        return ""
    return iso_str.split("T")[1][:5].replace(":", "h")


class SmilesMilesSearcher(FlightSearcher):
    AIRLINE_NAME = "SMILES"

    async def search(self, origin: str, destination: str, departure_date: date) -> List[Flight]:
        cached = _load_results_cache(origin, destination, departure_date)
        if cached is not None:
            logger.info(f"SMILES/{origin}→{destination} {departure_date}: {len(cached)} voos do cache")
            return cached
        logger.info(
            f"SMILES/{origin}→{destination} {departure_date}: "
            "sem cache — execute scripts/harvest_cookies.py"
        )
        return []

    async def search_range(
        self, origin: str, destination: str, days_ahead: int = 30, batch_size: int = 1
    ) -> List[Flight]:
        today = date.today()
        dates = [today + timedelta(days=i) for i in range(1, days_ahead + 1)]
        all_flights: List[Flight] = []
        cache_miss_logged = False

        for d in dates:
            cached = _load_results_cache(origin, destination, d)
            if cached is not None:
                all_flights.extend(cached)
            elif not cache_miss_logged:
                logger.info(
                    f"SMILES/{origin}→{destination}: "
                    "cache ausente ou expirado — execute scripts/harvest_cookies.py"
                )
                cache_miss_logged = True

        return all_flights

    def _parse(
        self, data: dict, origin: str, destination: str, departure_date: date
    ) -> List[Flight]:
        """Parses raw API JSON into Flight objects. Called by harvest_cookies.py."""
        flights: List[Flight] = []
        try:
            segments = data.get("requestedFlightSegmentList", [])
            for segment in segments:
                for flight_data in segment.get("flightList", []):
                    stops = int(flight_data.get("stops", 0))
                    if stops > 1:
                        continue

                    dep_time = _parse_time(flight_data.get("departure", {}).get("date", ""))
                    arr_time = _parse_time(flight_data.get("arrival", {}).get("date", ""))

                    booking_url = (
                        f"{_SEARCH_BASE}"
                        f"?originAirportCode={origin}"
                        f"&destinationAirportCode={destination}"
                        f"&departureDate={departure_date.strftime('%d/%m/%Y')}"
                        f"&adults=1&tripType=2"
                    )

                    for avail in flight_data.get("availabilityList", []):
                        if int(avail.get("quantity", 0)) <= 0:
                            continue
                        miles = avail.get("fare", {}).get("miles")
                        if miles is None:
                            continue

                        flights.append(Flight(
                            origin=origin,
                            destination=destination,
                            airline=self.AIRLINE_NAME,
                            departure_date=departure_date,
                            departure_time=dep_time,
                            arrival_time=arr_time,
                            price=0.0,
                            is_direct=(stops == 0),
                            stops=stops,
                            booking_url=booking_url,
                            miles=int(miles),
                        ))
        except Exception as e:
            logger.error(f"SMILES parse error: {e}", exc_info=True)
        return flights
