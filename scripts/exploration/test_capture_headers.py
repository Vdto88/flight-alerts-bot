"""
Captura TODOS os headers enviados na request para a API de busca do Smiles.
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
    captured_headers = None
    captured_url = None
    captured_response = None

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

        async def handle_request(request):
            nonlocal captured_headers, captured_url
            rurl = request.url
            if _SEARCH_HOST in rurl:
                captured_headers = dict(request.headers)
                captured_url = rurl
                print(f"\n[REQUEST CAPTURADO]")
                print(f"URL: {rurl[:120]}")
                print(f"Headers ({len(captured_headers)}):")
                for k, v in sorted(captured_headers.items()):
                    print(f"  {k}: {v[:100]}")

        async def handle_response(response):
            nonlocal captured_response
            rurl = response.url
            if _SEARCH_HOST in rurl:
                print(f"\n[RESPONSE] status={response.status} url={rurl[:100]}")
                try:
                    body = await response.body()
                    print(f"  body preview: {body[:200]}")
                    if response.status == 200:
                        data = response.json() if hasattr(response, 'json') else json.loads(body)
                        captured_response = data
                        print(f"  >>> VOOS CAPTURADOS!")
                except Exception as e:
                    print(f"  erro ao ler body: {e}")

        page.on("request", handle_request)
        page.on("response", handle_response)

        print(f"Navegando: {url[:80]}...")
        await page.goto(url, timeout=40000, wait_until="domcontentloaded")
        await asyncio.sleep(5)

        try:
            btn_rejeitar = page.locator("button:has-text('Rejeitar todos')").first
            if await btn_rejeitar.is_visible(timeout=3000):
                await btn_rejeitar.click()
                print("Cookie popup fechado")
        except Exception:
            pass

        print("Aguardando 90s...")
        await asyncio.sleep(90)
        await browser.close()

    if captured_headers:
        out = Path("scripts/smiles_request_headers.json")
        out.write_text(json.dumps({
            "url": captured_url,
            "headers": captured_headers,
        }, indent=2, ensure_ascii=False))
        print(f"\nHeaders salvos em: {out}")

    if captured_response:
        out2 = Path("scripts/smiles_response_data.json")
        out2.write_text(json.dumps(captured_response, indent=2, ensure_ascii=False))
        print(f"Resposta salva em: {out2}")


asyncio.run(main())
