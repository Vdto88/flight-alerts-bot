"""
Chama a API de busca do Smiles DIRETAMENTE com httpx.
Usa a x-api-key capturada via inspeção do browser.
"""
import asyncio
import json
from datetime import date, timedelta
from pathlib import Path

import httpx

ORIGIN = "CNF"
DEST = "IGU"
DEPARTURE = date.today() + timedelta(days=30)

_SEARCH_URL = "https://api-air-flightsearch-blue.smiles.com.br/v1/airlines/search"
_API_KEY = "aJqPU7xNHl9qN3NVZnPaJ208aPo2Bh2p2ZV844tw"


async def main():
    departure_fmt = DEPARTURE.strftime("%d/%m/%Y")

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
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/143.0.0.0 Safari/537.36"
        ),
    }

    print(f"Chamando API direta: {_SEARCH_URL}")
    print(f"Params: {params}")
    print()

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        r = await client.get(_SEARCH_URL, headers=headers, params=params)
        print(f"Status: {r.status_code}")
        print(f"Headers de resposta relevantes:")
        for k, v in r.headers.items():
            if k.lower() in ("content-type", "x-cache", "cf-cache-status", "server"):
                print(f"  {k}: {v}")
        print()

        if r.status_code == 200:
            data = r.json()
            print(f"Keys: {list(data.keys())}")

            if "requestedFlightSegmentList" in data:
                segs = data["requestedFlightSegmentList"]
                total = sum(len(s.get("flightList", [])) for s in segs)
                print(f"\nVOOS ENCONTRADOS: {total}")
                if segs and segs[0].get("flightList"):
                    f = segs[0]["flightList"][0]
                    print(f"Primeiro voo keys: {list(f.keys())}")
                    avails = f.get("availabilityList", [])
                    if avails:
                        print(f"availabilityList[0]: {json.dumps(avails[0], ensure_ascii=False)[:300]}")

            out = Path("scripts/direct_api_result.json")
            out.write_text(json.dumps(data, indent=2, ensure_ascii=False))
            print(f"\nSalvo em: {out}")
        else:
            print(f"Erro: {r.text[:300]}")


asyncio.run(main())
