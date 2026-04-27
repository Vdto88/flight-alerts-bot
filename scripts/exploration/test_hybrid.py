"""
Abordagem hibrida melhorada:
1. Playwright + stealth para obter cookies Akamai (_abck, ak_bmsc, etc.)
2. curl_cffi com esses cookies para chamar a API diretamente

E tambem tenta capturar a resposta via page.route() (mais confiavel que page.on("response")).
"""
import asyncio
import json
from datetime import date, timedelta
from pathlib import Path

from curl_cffi import requests as cffi_requests
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

ORIGIN = "CNF"
DEST = "IGU"
DEPARTURE = date.today() + timedelta(days=30)

_SEARCH_HOST = "api-air-flightsearch-blue.smiles.com.br"
_SEARCH_URL = f"https://{_SEARCH_HOST}/v1/airlines/search"
_API_KEY = "aJqPU7xNHl9qN3NVZnPaJ208aPo2Bh2p2ZV844tw"


async def main():
    route_response_data = None
    captured_cookies = {}

    departure_iso = DEPARTURE.strftime("%Y-%m-%d")
    import calendar
    from datetime import datetime
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
        context = await browser.new_context()
        page = await context.new_page()

        # Interceptar via route() — mais confiavel para capturar responses
        async def intercept_route(route, request):
            nonlocal route_response_data
            rurl = request.url
            if _SEARCH_HOST in rurl:
                print(f"\n[ROUTE INTERCEPT] {rurl[:100]}")
                try:
                    response = await route.fetch()
                    body = await response.body()
                    print(f"  status={response.status}, body_len={len(body)}")
                    if response.status == 200:
                        data = json.loads(body)
                        route_response_data = data
                        print(f"  >>> DADOS CAPTURADOS via route! Keys: {list(data.keys())[:6]}")
                    else:
                        print(f"  body: {body[:200]}")
                    await route.fulfill(response=response)
                except Exception as e:
                    print(f"  Erro no route intercept: {e}")
                    await route.continue_()
            else:
                await route.continue_()

        await page.route("**", intercept_route)

        print(f"Navegando: {mfe_url[:80]}...")
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

        print("Aguardando API responder (90s)...")
        for i in range(90):
            if route_response_data:
                print(f"\nResposta capturada em {i+1}s!")
                break
            await asyncio.sleep(1)
            if (i + 1) % 15 == 0:
                print(f"  ...{i+1}s sem resposta ainda")

        # Capturar cookies para uso posterior com curl_cffi
        cookies = await context.cookies()
        for c in cookies:
            if "smiles" in c.get("domain", "") or "akamai" in c.get("domain", ""):
                captured_cookies[c["name"]] = c["value"]

        print(f"\nCookies capturados: {list(captured_cookies.keys())}")

        # Screenshot
        await page.screenshot(path="scripts/hybrid_screenshot.png", full_page=False)
        print("Screenshot: scripts/hybrid_screenshot.png")
        await browser.close()

    if route_response_data:
        out = Path("scripts/hybrid_result.json")
        out.write_text(json.dumps(route_response_data, indent=2, ensure_ascii=False))
        print(f"\nDados salvos em: {out}")
        analyze_flights(route_response_data)
        return

    # Se nao capturou via route, tentar curl_cffi com cookies do browser
    if captured_cookies:
        print("\n\nTentando curl_cffi com cookies do browser...")
        cookie_str = "; ".join(f"{k}={v}" for k, v in captured_cookies.items())

        headers = {
            "x-api-key": _API_KEY,
            "channel": "WEB",
            "accept": "application/json, text/plain, */*",
            "referer": "https://www.smiles.com.br/",
            "cookie": cookie_str[:2000],
            "sec-ch-ua": '"Chrome";v="143", "Not?A?Brand";v="99", "Chromium";v="143"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        }

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

        try:
            r = cffi_requests.get(
                _SEARCH_URL,
                headers=headers,
                params=params,
                impersonate="chrome136",
                timeout=30,
            )
            print(f"curl_cffi status: {r.status_code}")
            if r.status_code == 200:
                data = r.json()
                out = Path("scripts/hybrid_cffi_result.json")
                out.write_text(json.dumps(data, indent=2, ensure_ascii=False))
                print(f"Salvo em: {out}")
                analyze_flights(data)
            else:
                print(f"Erro: {r.text[:300]}")
        except Exception as e:
            print(f"Erro curl_cffi: {e}")
    else:
        print("Nenhum dado capturado.")


def analyze_flights(data):
    if "requestedFlightSegmentList" in data:
        segs = data["requestedFlightSegmentList"]
        total = sum(len(s.get("flightList", [])) for s in segs)
        print(f"\n>>> VOOS: {total}")
        if segs and segs[0].get("flightList"):
            f0 = segs[0]["flightList"][0]
            print(f"Primeiro voo: {list(f0.keys())}")
            avails = f0.get("availabilityList", [])
            if avails:
                print(f"availabilityList[0]: {json.dumps(avails[0], ensure_ascii=False)[:400]}")
    else:
        print(f"Keys: {list(data.keys())}")


asyncio.run(main())
