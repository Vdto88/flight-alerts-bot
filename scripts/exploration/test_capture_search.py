"""
Captura a resposta da API real de busca de voos do Smiles:
  api-air-flightsearch-blue.smiles.com.br/v1/airlines/search
com x-api-key (nao Bearer token).
"""
import asyncio
import calendar
import json
from datetime import date, datetime, timedelta
from pathlib import Path

from playwright.async_api import async_playwright
from playwright_stealth import Stealth

ORIGIN = "CNF"
DEST = "IGU"
DEPARTURE = date.today() + timedelta(days=30)
_MFE_BASE = "https://www.smiles.com.br/mfe/emissao-passagem"
_SEARCH_HOST = "api-air-flightsearch-blue.smiles.com.br"


async def main():
    captured = []
    api_key_found = None

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
        page = await browser.new_page()

        # Interceptar requests para capturar a x-api-key
        async def handle_request(request):
            nonlocal api_key_found
            rurl = request.url
            if _SEARCH_HOST in rurl:
                headers = dict(request.headers)
                key = headers.get("x-api-key", "")
                if key:
                    api_key_found = key
                    print(f"  [REQ] {rurl[:100]}")
                    print(f"    x-api-key: {key}")

        # Interceptar respostas para capturar os dados de voos
        async def handle_response(response):
            rurl = response.url
            if _SEARCH_HOST in rurl and response.status == 200:
                print(f"  [RESP 200] {rurl[:100]}")
                try:
                    data = await response.json()
                    captured.append({"url": rurl, "data": data})
                    print(f"  >>> Resposta capturada! Keys: {list(data.keys())[:8]}")
                except Exception as e:
                    print(f"  >>> Erro JSON: {e}")
            elif _SEARCH_HOST in rurl:
                try:
                    body = await response.body()
                    print(f"  [RESP {response.status}] {rurl[:80]}")
                    print(f"    Body: {body[:120]}")
                except Exception:
                    print(f"  [RESP {response.status}] {rurl[:80]}")

        page.on("request", handle_request)
        page.on("response", handle_response)

        print(f"Navegando: {url[:80]}...")
        await page.goto(url, timeout=40000, wait_until="domcontentloaded")
        await asyncio.sleep(5)

        # Fechar o popup de cookies se aparecer
        try:
            btn_rejeitar = page.locator("button:has-text('Rejeitar todos')").first
            if await btn_rejeitar.is_visible(timeout=3000):
                await btn_rejeitar.click()
                print("  Cookie popup fechado (Rejeitar todos)")
        except Exception:
            pass

        # Aguardar os resultados carregarem (a busca dispara automaticamente)
        print("Aguardando busca e resultados (60s)...")
        await asyncio.sleep(60)

        # Screenshot
        await page.screenshot(path="scripts/smiles_results.png", full_page=False)
        print("Screenshot salvo: scripts/smiles_results.png")

        await browser.close()

    print(f"\n=== RESULTADO ===")
    print(f"API key capturada: {api_key_found}")
    print(f"Respostas capturadas: {len(captured)}")

    if captured:
        for item in captured:
            url = item.get("url", "")
            d = item.get("data", {})
            print(f"\nURL: {url[:90]}")
            print(f"Keys: {list(d.keys())}")

            # Mostrar estrutura de voos
            if "requestedFlightSegmentList" in d:
                segs = d["requestedFlightSegmentList"]
                total = sum(len(s.get("flightList", [])) for s in segs)
                print(f"VOOS (requestedFlightSegmentList): {total}")
                if segs and segs[0].get("flightList"):
                    f = segs[0]["flightList"][0]
                    print(f"Primeiro voo keys: {list(f.keys())}")
                    print(f"  stops: {f.get('stops')}")
                    print(f"  departure: {f.get('departure',{}).get('date','')}")
                    avails = f.get("availabilityList", [])
                    if avails:
                        print(f"  availabilityList[0]: {json.dumps(avails[0], ensure_ascii=False)[:200]}")

            out = Path("scripts/smiles_search_result.json")
            out.write_text(json.dumps(captured, indent=2, ensure_ascii=False))
            print(f"\nSalvo em: {out}")
    else:
        print("Nenhuma resposta de voos capturada.")
        if api_key_found:
            print(f"Mas temos a x-api-key: {api_key_found}")
            print("Tente chamar a API diretamente com essa chave.")


asyncio.run(main())
