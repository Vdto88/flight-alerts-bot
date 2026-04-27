"""
Teste rápido do playwright-stealth contra o Smiles.
Abre o browser VISÍVEL, aplica stealth, e verifica se a API retorna 200.

Uso:
    python scripts/test_stealth.py
"""
import asyncio
import calendar
import json
from datetime import date, datetime, timedelta
from pathlib import Path

from playwright.async_api import async_playwright
from playwright_stealth import Stealth

_MFE_BASE = "https://www.smiles.com.br/mfe/emissao-passagem"
_API_HOST = "api-air-flightsearch-blue.smiles.com.br"
_API_HOST_LEGACY = "flightavailability-prd.smiles.com.br"

ORIGIN = "CNF"
DEST = "IGU"
DEPARTURE = date.today() + timedelta(days=30)


async def main():
    captured = []
    blocked = []

    departure_ts = int(
        calendar.timegm(
            datetime(DEPARTURE.year, DEPARTURE.month, DEPARTURE.day).timetuple()
        )
    ) * 1000

    url = (
        f"{_MFE_BASE}"
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

        WATCH_HOSTS = [
            _API_HOST,                    # api-air-flightsearch-blue.smiles.com.br
            _API_HOST_LEGACY,             # flightavailability-prd.smiles.com.br
            "apigw-blue.smiles.com.br",   # novo gateway OAuth + possivelmente search
        ]

        async def handle_response(response):
            url = response.url
            # Logar TUDO de smiles.com.br (exceto estáticos)
            is_smiles = "smiles.com.br" in url
            is_static = any(x in url for x in ["/static/", ".js", ".css", ".svg", ".woff", ".png", ".jpg", "import.map"])
            if is_smiles and not is_static:
                print(f"  [{response.status}] {url[:110]}")
                if response.status == 200:
                    try:
                        data = await response.json()
                        captured.append({"url": url, "data": data})
                    except Exception:
                        pass
                elif response.status not in (200, 201, 202, 204):
                    blocked.append((response.status, url[:80]))

        page.on("response", handle_response)

        print(f"Abrindo: {url[:80]}...")
        print(f"Data de partida: {DEPARTURE}")
        print()

        await page.goto(url, timeout=30000, wait_until="domcontentloaded")
        print("Pagina carregada. Aguardando resposta da API (40s)...")
        await asyncio.sleep(40)

        await browser.close()

    print()
    if captured:
        print(f"OK Capturadas {len(captured)} resposta(s) JSON:")
        for i, item in enumerate(captured):
            url = item.get("url", "")
            d = item.get("data", {})
            print(f"  [{i}] {url[:80]}")
            print(f"       keys: {list(d.keys())[:8]}")
        # Salvar tudo
        out = Path("scripts/stealth_result.json")
        out.write_text(json.dumps(captured, indent=2, ensure_ascii=False))
        print(f"   Salvo em: {out}")
        # Verificar se tem dados de voos
        for item in captured:
            d = item.get("data", {})
            if "requestedFlightSegmentList" in d:
                segments = d["requestedFlightSegmentList"]
                total = sum(len(s.get("flightList", [])) for s in segments)
                print(f"   VOOS ENCONTRADOS: {total}")
            elif "flights" in d:
                print(f"   VOOS ENCONTRADOS: {len(d['flights'])}")
    if blocked:
        print(f"Respostas nao-200 de smiles.com.br:")
        for status, url in blocked:
            print(f"  [{status}] {url}")
    if not captured and not blocked:
        print("AVISO: Nenhuma requisicao de API detectada")
        print("   (pode ser que a URL mudou ou o site está fora)")


asyncio.run(main())
