"""
Usa curl_cffi para impersonar Chrome e chamar a API do Smiles diretamente.
curl_cffi replica o TLS fingerprint do Chrome, bypassando Akamai.
"""
import json
from datetime import date, timedelta
from pathlib import Path

from curl_cffi import requests

ORIGIN = "CNF"
DEST = "IGU"
DEPARTURE = date.today() + timedelta(days=30)

_SEARCH_URL = "https://api-air-flightsearch-blue.smiles.com.br/v1/airlines/search"
_API_KEY = "aJqPU7xNHl9qN3NVZnPaJ208aPo2Bh2p2ZV844tw"


def main():
    departure_iso = DEPARTURE.strftime("%Y-%m-%d")

    params = {
        "originAirportCode": ORIGIN,
        "destinationAirportCode": DEST,
        "departureDate": departure_iso,
        "memberNumber": "",
        "adults": "1",
        "children": "0",
        "infants": "0",
        "forceCongener": "false",
        "cookies": "_gid=undefined;",
    }

    headers = {
        "x-api-key": _API_KEY,
        "channel": "WEB",
        "accept": "application/json, text/plain, */*",
        "referer": "https://www.smiles.com.br/",
        "sec-ch-ua": '"Chrome";v="143", "Not?A?Brand";v="99", "Chromium";v="143"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    }

    print(f"Chamando API com curl_cffi (impersonate=chrome143)")
    print(f"URL: {_SEARCH_URL}")
    print(f"Params: {params}")
    print()

    # impersonate="chrome143" replica o JA3/JA4 TLS fingerprint do Chrome 143
    r = requests.get(
        _SEARCH_URL,
        headers=headers,
        params=params,
        impersonate="chrome136",
        timeout=30,
    )

    print(f"Status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"Keys: {list(data.keys())}")

        if "requestedFlightSegmentList" in data:
            segs = data["requestedFlightSegmentList"]
            total = sum(len(s.get("flightList", [])) for s in segs)
            print(f"\nVOOS ENCONTRADOS: {total}")
            if segs and segs[0].get("flightList"):
                f0 = segs[0]["flightList"][0]
                print(f"Primeiro voo keys: {list(f0.keys())}")
                avails = f0.get("availabilityList", [])
                if avails:
                    print(f"availabilityList[0]: {json.dumps(avails[0], ensure_ascii=False)[:400]}")

        out = Path("scripts/curl_cffi_result.json")
        out.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        print(f"\nSalvo em: {out}")
    else:
        print(f"Erro {r.status_code}: {r.text[:400]}")


main()
