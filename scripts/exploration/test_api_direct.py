"""
Abordagem hibrida:
1. Playwright + stealth para obter o token OAuth
2. httpx para chamar a API de voos diretamente com o token

Isso evita ter que lidar com o MFE React + anti-bot ao mesmo tempo.
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

# Endpoints a testar (em ordem de probabilidade)
SEARCH_ENDPOINTS = [
    # Novo gateway
    "https://apigw-blue.smiles.com.br/v1/flights/availability",
    "https://apigw-blue.smiles.com.br/v1/flights",
    "https://apigw-blue.smiles.com.br/v1/availability/flights",
    "https://apigw-blue.smiles.com.br/v1/search/flights",
    # Endpoint legado que funcionava antes
    "https://flightavailability-prd.smiles.com.br/flight/category",
    "https://flightavailability-prd.smiles.com.br/v1/flights",
    # Outro host novo
    "https://api-air-flightsearch-blue.smiles.com.br/v1/flights",
    "https://api-air-flightsearch-blue.smiles.com.br/v1/availability",
]


async def get_oauth_token() -> str:
    """Usa Playwright+stealth para capturar o token OAuth do Smiles."""
    token = None

    async with Stealth().use_async(async_playwright()) as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        async def handle_response(response):
            nonlocal token
            url = response.url
            # Debug: mostrar todas as chamadas de API
            if "smiles.com.br" in url and "static" not in url and ".js" not in url:
                print(f"  [{response.status}] {url[:90]}")
            if "oauth" in url and response.status == 200:
                try:
                    data = await response.json()
                    token = data.get("access_token")
                    if token:
                        print(f"  >>> Token obtido: {token[:40]}...")
                except Exception as e:
                    print(f"  >>> Erro ao parsear token: {e}")

        page.on("response", handle_response)

        # Navegar para o MFE — só precisamos que ele dispare o OAuth
        departure_ts = int(
            calendar.timegm(
                datetime(DEPARTURE.year, DEPARTURE.month, DEPARTURE.day).timetuple()
            )
        ) * 1000
        url = (
            f"https://www.smiles.com.br/mfe/emissao-passagem"
            f"?tripType=2&originAirport={ORIGIN}&destinationAirport={DEST}"
            f"&departureDate={departure_ts}&adults=1"
        )

        await page.goto(url, timeout=30000, wait_until="domcontentloaded")

        # Esperar apenas o token (não precisa esperar a busca inteira)
        print("  Aguardando token OAuth (max 60s)...")
        for i in range(60):
            if token:
                break
            if i % 10 == 9:
                print(f"  ... {i+1}s sem token ainda")
            await asyncio.sleep(1)

        await browser.close()

    return token


async def search_flights(token: str) -> dict:
    """Tenta chamar cada endpoint de busca com o token OAuth."""
    departure_date_str = DEPARTURE.strftime("%Y-%m-%d")
    departure_date_api = DEPARTURE.strftime("%d/%m/%Y")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": "https://www.smiles.com.br",
        "Referer": "https://www.smiles.com.br/",
        "x-api-key": "aJqe9OWPkA7RRGsINEuMnrVblhVmMDol",  # chave vista nas requests antigas
    }

    # Params comuns de busca
    params_get = {
        "originAirportCode": ORIGIN,
        "destinationAirportCode": DEST,
        "departureDate": departure_date_api,
        "adults": "1",
        "children": "0",
        "infants": "0",
        "tripType": "2",
        "cabinType": "all",
        "currencyCode": "BRL",
        "isFlexibleDateChecked": "false",
    }

    body_post = {
        "originAirportCode": ORIGIN,
        "destinationAirportCode": DEST,
        "departureDate": departure_date_str,
        "adults": 1,
        "children": 0,
        "infants": 0,
        "tripType": 2,
        "cabinType": "all",
    }

    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        for endpoint in SEARCH_ENDPOINTS:
            # Tentar GET
            try:
                print(f"\n  GET {endpoint[:70]}...")
                r = await client.get(endpoint, headers=headers, params=params_get)
                print(f"    Status: {r.status_code}")
                if r.status_code == 200:
                    data = r.json()
                    print(f"    Keys: {list(data.keys())[:8]}")
                    return {"url": endpoint, "method": "GET", "data": data}
                elif r.status_code not in (404, 405):
                    print(f"    Body: {r.text[:100]}")
            except Exception as e:
                print(f"    Erro: {e}")

            # Tentar POST
            try:
                print(f"  POST {endpoint[:70]}...")
                r = await client.post(endpoint, headers=headers, json=body_post)
                print(f"    Status: {r.status_code}")
                if r.status_code == 200:
                    data = r.json()
                    print(f"    Keys: {list(data.keys())[:8]}")
                    return {"url": endpoint, "method": "POST", "data": data}
                elif r.status_code not in (404, 405):
                    print(f"    Body: {r.text[:100]}")
            except Exception as e:
                print(f"    Erro: {e}")

    return {}


async def main():
    print("=== FASE 1: Obtendo token OAuth via Playwright+stealth ===")
    token = await get_oauth_token()

    if not token:
        print("Falha ao obter token OAuth")
        return

    print(f"\nToken obtido com sucesso!")
    print("\n=== FASE 2: Chamando API de voos diretamente ===")
    result = await search_flights(token)

    if result:
        print(f"\n>>> SUCESSO: {result['method']} {result['url']}")
        out = Path("scripts/api_direct_result.json")
        out.write_text(json.dumps(result, indent=2, ensure_ascii=False))
        print(f"Resultado salvo em: {out}")

        d = result.get("data", {})
        # Mostrar estrutura
        if "requestedFlightSegmentList" in d:
            segs = d["requestedFlightSegmentList"]
            total = sum(len(s.get("flightList", [])) for s in segs)
            print(f"\nVoos encontrados: {total}")
        elif "flightCategoryList" in d:
            cats = d["flightCategoryList"]
            total = sum(len(c.get("flightList", [])) for c in cats)
            print(f"\nVoos (flightCategoryList): {total}")
    else:
        print("\nNenhum endpoint funcionou com o token OAuth.")
        print("Precisamos inspecionar o network traffic manualmente.")


asyncio.run(main())
