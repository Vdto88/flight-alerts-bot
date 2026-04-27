"""
Diagnostica o estado da sessao Akamai:
- Verifica valor do cookie _abck (formato indica se e valido ou rejeitado)
- Tenta fazer a request com requestfinished/requestfailed events
- Verifica se ha algum outro endpoint que funciona
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
        context = await browser.new_context()
        page = await context.new_page()

        search_requests = []
        search_responses = []
        failed_requests = []

        async def on_request(request):
            if "airlines/search" in request.url or "flightavail" in request.url:
                search_requests.append(request.url)
                print(f"[REQ] {request.url[:120]}")

        async def on_response(response):
            if "airlines/search" in response.url or "flightavail" in response.url:
                search_responses.append((response.url, response.status))
                print(f"[RESP {response.status}] {response.url[:100]}")
                try:
                    body = await response.body()
                    print(f"  body: {body[:200]}")
                except Exception as e:
                    print(f"  body err: {e}")

        async def on_request_finished(request):
            if "smiles.com.br" in request.url and "airlines" in request.url:
                print(f"[FINISHED] {request.url[:100]}")
                try:
                    resp = await request.response()
                    if resp:
                        print(f"  -> status={resp.status}")
                        body = await resp.body()
                        print(f"  -> body: {body[:200]}")
                except Exception as e:
                    print(f"  -> err: {e}")

        async def on_request_failed(request):
            if "smiles.com.br" in request.url:
                print(f"[FAILED] {request.url[:100]} | {request.failure}")

        context.on("request", on_request)
        context.on("response", on_response)
        context.on("requestfinished", on_request_finished)
        context.on("requestfailed", on_request_failed)

        # Primeiro visitar homepage para aquecer sessao
        print("Visitando homepage...")
        await page.goto("https://www.smiles.com.br", timeout=30000, wait_until="domcontentloaded")
        await asyncio.sleep(5)

        print("\nNavigating to MFE...")
        await page.goto(mfe_url, timeout=40000, wait_until="domcontentloaded")
        await asyncio.sleep(5)

        try:
            btn = page.locator("button:has-text('Rejeitar todos')").first
            if await btn.is_visible(timeout=3000):
                await btn.click()
                print("Cookie popup fechado")
        except Exception:
            pass

        print("\nAguardando 30s...")
        await asyncio.sleep(30)

        # Capturar cookies Akamai
        cookies = await context.cookies()
        akamai_cookies = {c["name"]: c["value"] for c in cookies
                         if c["name"] in ("_abck", "ak_bmsc", "bm_sz", "bm_sv")}

        print(f"\n=== COOKIES AKAMAI ===")
        for name, value in akamai_cookies.items():
            print(f"{name}: {value[:100]}...")

        # Analisar _abck
        abck = akamai_cookies.get("_abck", "")
        if abck:
            parts = abck.split("~")
            print(f"\n_abck partes ({len(parts)}): {parts[-3:] if len(parts) > 3 else parts}")
            # Se termina com ~0~-1~-1 ou similar, sessao rejeitada
            if len(parts) >= 2:
                last_parts = "~".join(parts[-3:]) if len(parts) >= 3 else "~".join(parts)
                print(f"Ultimas partes: {last_parts}")
                if "-1~-1" in last_parts:
                    print("SESSAO REJEITADA (bot detectado)")
                else:
                    print("Sessao possivelmente valida")

        print(f"\nRequests de busca feitas: {len(search_requests)}")
        print(f"Responses recebidas: {len(search_responses)}")
        print(f"Requests falhas: {len(failed_requests)}")

        await page.screenshot(path="scripts/akamai_debug.png", full_page=False)
        await browser.close()


asyncio.run(main())
