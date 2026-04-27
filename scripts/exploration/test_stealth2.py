"""
Teste stealth v2 — espera o formulario carregar e clica em Buscar.
Monitora todas as chamadas de API do Smiles apos o clique.
"""
import asyncio
import calendar
import json
from datetime import date, datetime, timedelta
from pathlib import Path

from playwright.async_api import async_playwright
from playwright_stealth import Stealth

_API_HOSTS = [
    "api-air-flightsearch-blue.smiles.com.br",
    "flightavailability-prd.smiles.com.br",
    "apigw-blue.smiles.com.br",
]

ORIGIN = "CNF"
DEST = "IGU"
DEPARTURE = date.today() + timedelta(days=30)


async def main():
    captured = []

    departure_ts = int(
        calendar.timegm(
            datetime(DEPARTURE.year, DEPARTURE.month, DEPARTURE.day).timetuple()
        )
    ) * 1000

    url = (
        "https://www.smiles.com.br/mfe/emissao-passagem"
        f"?tripType=2"
        f"&originAirport={ORIGIN}"
        f"&destinationAirport={DEST}"
        f"&departureDate={departure_ts}"
        f"&adults=1&children=0&infants=0"
        f"&cabinType=all&isFlexibleDateChecked=false"
    )

    async with Stealth().use_async(async_playwright()) as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        async def handle_response(response):
            rurl = response.url
            is_api = any(h in rurl for h in _API_HOSTS)
            is_smiles_json = "smiles.com.br" in rurl and "json" in response.headers.get("content-type", "")
            if is_api or is_smiles_json:
                print(f"  [{response.status}] {rurl[:100]}")
                if response.status == 200:
                    try:
                        data = await response.json()
                        captured.append({"url": rurl, "data": data})
                    except Exception:
                        pass

        page.on("response", handle_response)

        print(f"Navegando para: {url[:80]}...")
        await page.goto(url, timeout=40000, wait_until="domcontentloaded")

        # Esperar o formulário de busca carregar (MFE demora alguns segundos)
        print("Aguardando formulario de busca carregar (15s)...")
        await asyncio.sleep(15)

        # Tentar encontrar e clicar o botao de busca
        search_selectors = [
            "button[data-testid='search-button']",
            "button:has-text('Buscar')",
            "button:has-text('buscar')",
            "button:has-text('Pesquisar')",
            "input[type='submit']",
            ".search-button",
            "#btnBuscar",
            "button.btn-search",
        ]

        clicked = False
        for sel in search_selectors:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=2000):
                    print(f"Botao encontrado: {sel}")
                    await btn.click()
                    clicked = True
                    break
            except Exception:
                continue

        if not clicked:
            print("Botao de busca nao encontrado — aguardando mais 20s para busca automatica...")

        print("Aguardando resposta da API (20s)...")
        await asyncio.sleep(20)

        await browser.close()

    print()
    if captured:
        print(f"Capturadas {len(captured)} resposta(s):")
        for item in captured:
            u = item.get("url", "")
            d = item.get("data", {})
            keys = list(d.keys()) if isinstance(d, dict) else type(d).__name__
            print(f"  {u[:90]}")
            print(f"    keys: {keys[:8]}")

        out = Path("scripts/stealth_result2.json")
        out.write_text(json.dumps(captured, indent=2, ensure_ascii=False))
        print(f"\nSalvo em: {out}")

        # Verificar voos
        for item in captured:
            d = item.get("data", {})
            if isinstance(d, dict):
                if "requestedFlightSegmentList" in d:
                    segs = d["requestedFlightSegmentList"]
                    total = sum(len(s.get("flightList", [])) for s in segs)
                    print(f"\n>>> VOOS encontrados (requestedFlightSegmentList): {total}")
                elif "flightCategoryList" in d:
                    cats = d["flightCategoryList"]
                    total = sum(len(c.get("flightList", [])) for c in cats)
                    print(f"\n>>> VOOS encontrados (flightCategoryList): {total}")
    else:
        print("Nenhuma resposta de API capturada.")
        print("Verifique o browser — pode precisar fazer a busca manualmente.")


asyncio.run(main())
