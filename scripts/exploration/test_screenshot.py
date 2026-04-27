"""
Captura screenshot da pagina do Smiles apos carregar com stealth.
Tambem intercepta requests (nao responses) para ver os headers que o browser envia.
"""
import asyncio
import calendar
from datetime import date, datetime, timedelta
from pathlib import Path

from playwright.async_api import async_playwright
from playwright_stealth import Stealth

ORIGIN = "CNF"
DEST = "IGU"
DEPARTURE = date.today() + timedelta(days=30)

_MFE_BASE = "https://www.smiles.com.br/mfe/emissao-passagem"


async def main():
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

        # Interceptar REQUESTS para ver os headers enviados para a API
        async def handle_request(request):
            rurl = request.url
            if "smiles.com.br" in rurl and "static" not in rurl and ".js" not in rurl and ".css" not in rurl:
                method = request.method
                headers = dict(request.headers)
                # Mostrar headers relevantes
                auth = headers.get("authorization", "")
                api_key = headers.get("x-api-key", "")
                if auth or api_key or "flight" in rurl or "api" in rurl.lower():
                    print(f"\n  [{method}] {rurl[:90]}")
                    if auth:
                        print(f"    Authorization: {auth[:60]}...")
                    if api_key:
                        print(f"    x-api-key: {api_key}")

        page.on("request", handle_request)

        print(f"Navegando: {url[:80]}...")
        await page.goto(url, timeout=40000, wait_until="domcontentloaded")

        print("Aguardando 35s...")
        await asyncio.sleep(35)

        # Screenshot
        shot = Path("scripts/smiles_screenshot.png")
        await page.screenshot(path=str(shot), full_page=True)
        print(f"\nScreenshot salvo: {shot}")

        # Tentar listar todos os botoes visiveis na pagina
        buttons = await page.locator("button").all()
        print(f"\nBotoes na pagina: {len(buttons)}")
        for i, btn in enumerate(buttons[:10]):
            try:
                text = await btn.inner_text()
                visible = await btn.is_visible()
                if visible:
                    print(f"  [{i}] '{text.strip()[:40]}' visible={visible}")
            except Exception:
                pass

        await browser.close()


asyncio.run(main())
