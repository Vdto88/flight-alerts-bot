"""
Stealth v3 — captura token OAuth E tenta chamar a API de busca.
Baseia-se no test_stealth.py que funcionou (aguarda 40s).
"""
import asyncio
import calendar
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

ORIGIN = "CNF"
DEST = "IGU"
DEPARTURE = date.today() + timedelta(days=30)

_MFE_BASE = "https://www.smiles.com.br/mfe/emissao-passagem"
_API_HOSTS = [
    "api-air-flightsearch-blue.smiles.com.br",
    "flightavailability-prd.smiles.com.br",
    "apigw-blue.smiles.com.br",
]


async def main():
    captured_responses = []
    oauth_token = None
    oauth_cookies = {}

    departure_ts = int(
        calendar.timegm(
            datetime(DEPARTURE.year, DEPARTURE.month, DEPARTURE.day).timetuple()
        )
    ) * 1000
    url = (
        f"{_MFE_BASE}?tripType=2"
        f"&originAirport={ORIGIN}&destinationAirport={DEST}"
        f"&departureDate={departure_ts}"
        f"&adults=1&children=0&infants=0"
        f"&cabinType=all&isFlexibleDateChecked=false"
    )

    async with Stealth().use_async(async_playwright()) as p:
        browser = await p.chromium.launch(headless=False)
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = await browser.new_page()

        FLIGHT_HOSTS = [
            "api-air-flightsearch-blue.smiles.com.br",
            "flightavailability-prd.smiles.com.br",
        ]

        async def handle_response(response):
            nonlocal oauth_token
            rurl = response.url
            if "smiles.com.br" in rurl and "static" not in rurl and ".js" not in rurl:
                print(f"  [{response.status}] {rurl[:100]}")
            # Token OAuth
            if "oauth" in rurl and "apigw-blue" in rurl and response.status == 200:
                try:
                    data = await response.json()
                    t = data.get("access_token")
                    if t:
                        oauth_token = t
                        print(f"  >>> TOKEN CAPTURADO!")
                except Exception:
                    pass
            # Respostas de voos (apenas hosts de busca de voos, não oauth)
            if any(h in rurl for h in FLIGHT_HOSTS) and response.status == 200:
                try:
                    data = await response.json()
                    captured_responses.append({"url": rurl, "data": data})
                    print(f"  >>> VOOS CAPTURADOS de {rurl[:60]}")
                except Exception:
                    pass
            # Também monitorar apigw-blue para outros endpoints (exceto oauth/token)
            if "apigw-blue.smiles.com.br" in rurl and "oauth" not in rurl and response.status == 200:
                try:
                    data = await response.json()
                    captured_responses.append({"url": rurl, "data": data})
                    print(f"  >>> API APIGW CAPTURADA: {rurl[:60]}")
                except Exception:
                    pass

        page.on("response", handle_response)

        print(f"Navegando: {url[:80]}...")
        await page.goto(url, timeout=40000, wait_until="domcontentloaded")
        print("Aguardando 60s para MFE carregar e busca disparar...")
        await asyncio.sleep(60)

        # Se já temos voos, ótimo. Se não, tenta chamar a API com o token
        if not captured_responses and oauth_token:
            print("\nBusca não disparou automaticamente. Tentando API direta com token...")

            # Pegar cookies da sessão
            cookies = await context.cookies()
            cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies if "smiles" in c.get("domain",""))

            headers = {
                "Authorization": f"Bearer {oauth_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Origin": "https://www.smiles.com.br",
                "Referer": url,
                "Cookie": cookie_str[:500],
                "x-api-key": "aJqe9OWPkA7RRGsINEuMnrVblhVmMDol",
            }

            departure_fmt = DEPARTURE.strftime("%d/%m/%Y")
            search_urls = [
                f"https://flightavailability-prd.smiles.com.br/flight/category?originAirportCode={ORIGIN}&destinationAirportCode={DEST}&departureDate={departure_fmt}&adults=1&children=0&infants=0&tripType=2&cabinType=all&currencyCode=BRL",
                f"https://apigw-blue.smiles.com.br/v1/flights/availability?originAirportCode={ORIGIN}&destinationAirportCode={DEST}&departureDate={departure_fmt}&adults=1",
                f"https://api-air-flightsearch-blue.smiles.com.br/v1/flights?originAirportCode={ORIGIN}&destinationAirportCode={DEST}&departureDate={departure_fmt}&adults=1&tripType=2&cabinType=all",
            ]

            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                for search_url in search_urls:
                    print(f"  Testando: {search_url[:80]}")
                    try:
                        r = await client.get(search_url, headers=headers)
                        print(f"    Status: {r.status_code}")
                        if r.status_code == 200:
                            data = r.json()
                            captured_responses.append({"url": search_url, "data": data, "via": "httpx"})
                            print(f"    Keys: {list(data.keys())[:8]}")
                            break
                        else:
                            print(f"    Body: {r.text[:80]}")
                    except Exception as e:
                        print(f"    Erro: {e}")

        await browser.close()

    print("\n=== RESULTADO ===")
    if captured_responses:
        for item in captured_responses:
            print(f"URL: {item.get('url','')[:80]}")
            d = item.get("data", {})
            print(f"Keys: {list(d.keys())[:8]}")

            # Verificar estruturas de voos conhecidas
            if "requestedFlightSegmentList" in d:
                segs = d["requestedFlightSegmentList"]
                total = sum(len(s.get("flightList", [])) for s in segs)
                print(f">>> VOOS (requestedFlightSegmentList): {total}")
            elif "flightCategoryList" in d:
                cats = d["flightCategoryList"]
                total = sum(len(c.get("flightList", [])) for c in cats)
                print(f">>> VOOS (flightCategoryList): {total}")

        out = Path("scripts/stealth3_result.json")
        out.write_text(json.dumps(captured_responses, indent=2, ensure_ascii=False))
        print(f"\nSalvo em: {out}")
    else:
        print("Nenhum dado de voos capturado.")
        if oauth_token:
            print("Token obtido mas API não respondeu.")
        else:
            print("Token OAuth nao capturado.")


asyncio.run(main())
