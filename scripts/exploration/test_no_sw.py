"""
Desativa service workers e captura a resposta da API de busca do Smiles.
Service workers podem cachear respostas e impedir captura via page.on("response").
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
_SEARCH_HOST = "api-air-flightsearch-blue.smiles.com.br"


async def main():
    captured_key = None
    captured_data = None

    departure_ts = int(
        calendar.timegm(
            datetime(DEPARTURE.year, DEPARTURE.month, DEPARTURE.day).timetuple()
        )
    ) * 1000

    mfe_url = (
        f"https://www.smiles.com.br/mfe/emissao-passagem"
        f"?tripType=2&originAirport={ORIGIN}&destinationAirport={DEST}"
        f"&departureDate={departure_ts}&adults=1&children=0&infants=0"
        f"&cabinType=all&isFlexibleDateChecked=false"
    )

    async with Stealth().use_async(async_playwright()) as p:
        browser = await p.chromium.launch(headless=False)
        # service_workers="block" impede que o SW intercepte requests/responses
        context = await browser.new_context(service_workers="block")
        page = await context.new_page()

        async def handle_request(request):
            nonlocal captured_key
            rurl = request.url
            if _SEARCH_HOST in rurl:
                headers = dict(request.headers)
                key = headers.get("x-api-key", "")
                if key:
                    captured_key = key
                    print(f"\n[REQ] {rurl[:110]}")
                    print(f"  x-api-key: {key}")
                    print(f"  Todos os headers: {list(headers.keys())}")

        async def handle_response(response):
            nonlocal captured_data
            rurl = response.url
            if _SEARCH_HOST in rurl:
                print(f"\n[RESP {response.status}] {rurl[:100]}")
                try:
                    body = await response.body()
                    print(f"  body_len={len(body)}")
                    print(f"  body preview: {body[:200]}")
                    if response.status == 200:
                        captured_data = json.loads(body)
                        print(f"  >>> DADOS CAPTURADOS! Keys: {list(captured_data.keys())[:6]}")
                except Exception as e:
                    print(f"  Erro ao ler body: {e}")

        # Usar context.on para capturar requests/responses de TODOS os frames e workers
        context.on("request", handle_request)
        context.on("response", handle_response)

        print(f"Navegando (sem service workers): {mfe_url[:80]}...")
        await page.goto(mfe_url, timeout=40000, wait_until="domcontentloaded")
        await asyncio.sleep(5)

        # Fechar popup de cookies
        try:
            btn = page.locator("button:has-text('Rejeitar todos')").first
            if await btn.is_visible(timeout=3000):
                await btn.click()
                print("Cookie popup fechado")
        except Exception:
            pass

        print("\nAguardando API responder (90s)...")
        for i in range(90):
            if captured_data:
                print(f"\nResposta capturada em {i+1}s!")
                break
            await asyncio.sleep(1)
            if (i + 1) % 20 == 0:
                print(f"  ...{i+1}s, key={captured_key is not None}, data={captured_data is not None}")

        await page.screenshot(path="scripts/nosw_screenshot.png", full_page=False)
        print("Screenshot: scripts/nosw_screenshot.png")
        await browser.close()

    if captured_data:
        out = Path("scripts/nosw_result.json")
        out.write_text(json.dumps(captured_data, indent=2, ensure_ascii=False))
        print(f"Dados salvos em: {out}")

        if "requestedFlightSegmentList" in captured_data:
            segs = captured_data["requestedFlightSegmentList"]
            total = sum(len(s.get("flightList", [])) for s in segs)
            print(f"\nVOOS ENCONTRADOS: {total}")
            if segs and segs[0].get("flightList"):
                f0 = segs[0]["flightList"][0]
                avails = f0.get("availabilityList", [])
                if avails:
                    print(f"Primeiro voo milhas: {json.dumps(avails[0], ensure_ascii=False)[:400]}")
    else:
        print("\nNenhum dado capturado.")
        if captured_key:
            print(f"x-api-key capturada: {captured_key}")
            print("A API respondeu 406 — chave ou sessao invalida.")


asyncio.run(main())
