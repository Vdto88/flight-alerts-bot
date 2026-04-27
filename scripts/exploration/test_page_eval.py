"""
Usa page.evaluate() para fazer a chamada da API de dentro do browser.
Isso garante que os cookies, headers e TLS do browser sao usados.
Tambem captura a URL exata que o MFE usa para a busca.
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


async def main():
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
        context = await browser.new_context(service_workers="block")
        page = await context.new_page()

        # Capturar a URL exata e headers que o MFE usa
        search_request_info = {}

        async def handle_request(request):
            rurl = request.url
            if "api-air-flightsearch-blue.smiles.com.br" in rurl:
                search_request_info["url"] = rurl
                search_request_info["headers"] = dict(request.headers)
                print(f"\n[MFE usou URL]: {rurl[:120]}")

        context.on("request", handle_request)

        print(f"Carregando MFE...")
        await page.goto(mfe_url, timeout=40000, wait_until="domcontentloaded")
        await asyncio.sleep(5)

        try:
            btn = page.locator("button:has-text('Rejeitar todos')").first
            if await btn.is_visible(timeout=3000):
                await btn.click()
                print("Cookie popup fechado")
        except Exception:
            pass

        # Aguardar a URL ser capturada
        print("Aguardando MFE fazer a busca (30s)...")
        for i in range(30):
            if search_request_info.get("url"):
                break
            await asyncio.sleep(1)

        if not search_request_info.get("url"):
            print("URL nao capturada, usando URL padrao")
            departure_iso = DEPARTURE.strftime("%Y-%m-%d")
            search_url = (
                f"https://api-air-flightsearch-blue.smiles.com.br/v1/airlines/search"
                f"?originAirportCode={ORIGIN}&destinationAirportCode={DEST}"
                f"&departureDate={departure_iso}&memberNumber=&adults=1&children=0&infants=0"
                f"&forceCongener=false"
            )
            api_key = "aJqPU7xNHl9qN3NVZnPaJ208aPo2Bh2p2ZV844tw"
        else:
            search_url = search_request_info["url"]
            api_key = search_request_info["headers"].get("x-api-key", "aJqPU7xNHl9qN3NVZnPaJ208aPo2Bh2p2ZV844tw")

        print(f"\nFazendo chamada via page.evaluate()...")
        print(f"URL: {search_url[:120]}")
        print(f"x-api-key: {api_key}")

        # Executar fetch de dentro do browser — usa cookies e sessao do browser
        js_code = f"""
        async () => {{
            try {{
                const resp = await fetch({json.dumps(search_url)}, {{
                    method: 'GET',
                    headers: {{
                        'x-api-key': {json.dumps(api_key)},
                        'channel': 'WEB',
                        'accept': 'application/json, text/plain, */*',
                        'referer': 'https://www.smiles.com.br/',
                    }}
                }});
                const status = resp.status;
                if (status === 200) {{
                    const data = await resp.json();
                    return {{ status, data }};
                }} else {{
                    const text = await resp.text();
                    return {{ status, error: text.substring(0, 300) }};
                }}
            }} catch(e) {{
                return {{ status: 0, error: e.message }};
            }}
        }}
        """

        result = await page.evaluate(js_code)
        print(f"\nResultado do page.evaluate:")
        print(f"Status: {result.get('status')}")

        if result.get("status") == 200:
            data = result.get("data", {})
            print(f"Keys: {list(data.keys())[:8]}")

            if "requestedFlightSegmentList" in data:
                segs = data["requestedFlightSegmentList"]
                total = sum(len(s.get("flightList", [])) for s in segs)
                print(f"\nVOOS ENCONTRADOS: {total}")
                if segs and segs[0].get("flightList"):
                    f0 = segs[0]["flightList"][0]
                    avails = f0.get("availabilityList", [])
                    if avails:
                        print(f"avails[0]: {json.dumps(avails[0], ensure_ascii=False)[:400]}")

            out = Path("scripts/eval_result.json")
            out.write_text(json.dumps(data, indent=2, ensure_ascii=False))
            print(f"Salvo em: {out}")
        else:
            print(f"Erro: {result.get('error', 'desconhecido')}")

        await page.screenshot(path="scripts/eval_screenshot.png", full_page=False)
        print("\nScreenshot: scripts/eval_screenshot.png")
        await browser.close()


asyncio.run(main())
