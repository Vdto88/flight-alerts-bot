"""
Busca voos no Smiles usando o Chrome real, evitando detecção da Akamai.

Como usar:
  1. Execute: python scripts/harvest_cookies.py
  2. No Chrome que abrir, navegue pelo Smiles por ~15s (role a página)
  3. Pressione Enter — o script faz as buscas automaticamente
  4. Resultados salvos em scripts/smiles_cache.json por ~2h

O bot usa o cache automaticamente até ele expirar.
"""
import asyncio
import calendar
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import MILES_ROUTES, MILES_DAYS_AHEAD
from airlines.smiles_miles import SmilesMilesSearcher, _API_HOST

CACHE_FILE = Path(__file__).parent / "smiles_cache.json"
CDP_PORT = 9223

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]


def find_chrome() -> str | None:
    for path in CHROME_CANDIDATES:
        if Path(path).exists():
            return path
    return None


def mfe_url(origin: str, dest: str, departure: date) -> str:
    ts = int(
        calendar.timegm(
            datetime(departure.year, departure.month, departure.day).timetuple()
        )
    ) * 1000
    return (
        f"https://www.smiles.com.br/mfe/emissao-passagem"
        f"?tripType=2&originAirport={origin}&destinationAirport={dest}"
        f"&departureDate={ts}&adults=1&children=0&infants=0"
        f"&cabinType=all&isFlexibleDateChecked=false"
    )


async def search_one(page, origin: str, dest: str, departure: date) -> list:
    """Navega para o MFE no Chrome real e captura a resposta da API."""
    captured = {}

    async def on_response(r):
        if _API_HOST in r.url and r.status == 200:
            try:
                captured["data"] = await r.json()
            except Exception:
                pass

    page.on("response", on_response)
    try:
        await page.goto(mfe_url(origin, dest, departure), wait_until="domcontentloaded", timeout=30000)
        # Espera a API responder (máx 20s)
        for _ in range(20):
            if "data" in captured:
                break
            await asyncio.sleep(1)
    finally:
        page.remove_listener("response", on_response)

    if "data" not in captured:
        return []

    searcher = SmilesMilesSearcher()
    return searcher._parse(captured["data"], origin, dest, departure)


async def main():
    chrome = find_chrome()
    if not chrome:
        print("Chrome não encontrado. Instale o Google Chrome.")
        sys.exit(1)

    smiles_routes = [r for r in MILES_ROUTES if r.get("program") == "SMILES"]
    if not smiles_routes:
        print("Nenhuma rota SMILES configurada em config.py")
        sys.exit(0)

    print("=" * 60)
    print("  Busca Smiles via Chrome real")
    print("=" * 60)
    print()
    print("Abrindo Chrome...")
    print()
    print("Instruções:")
    print("  1. Role a página do Smiles por ~15 segundos")
    print("  2. Mova o mouse pelo site")
    print("  3. Depois volte aqui e pressione Enter")
    print()

    with tempfile.TemporaryDirectory() as tmpdir:
        proc = subprocess.Popen(
            [
                chrome,
                f"--remote-debugging-port={CDP_PORT}",
                f"--user-data-dir={tmpdir}",
                "--window-size=1280,900",
                "--no-first-run",
                "--no-default-browser-check",
                "https://www.smiles.com.br",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(2)

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, input, "Pressione Enter para iniciar as buscas...")

        today = date.today()
        dates = [today + timedelta(days=i) for i in range(1, MILES_DAYS_AHEAD + 1)]
        total = len(smiles_routes) * len(dates)

        all_flights = []
        cache_entries = {}

        try:
            async with async_playwright() as p:
                browser = await p.chromium.connect_over_cdp(
                    f"http://localhost:{CDP_PORT}", timeout=5000
                )
                context = browser.contexts[0]
                page = await context.new_page()

                done = 0
                for route in smiles_routes:
                    orig, dest = route["from"], route["to"]
                    for d in dates:
                        done += 1
                        print(f"  [{done}/{total}] {orig}→{dest} {d}...", end=" ", flush=True)
                        flights = await search_one(page, orig, dest, d)
                        if flights:
                            print(f"{len(flights)} voos (min {min(f.miles for f in flights):,} milhas)")
                            all_flights.extend(flights)
                            key = f"{orig}-{dest}-{d}"
                            cache_entries[key] = [
                                {
                                    "origin": f.origin,
                                    "destination": f.destination,
                                    "departure_date": str(f.departure_date),
                                    "departure_time": f.departure_time,
                                    "arrival_time": f.arrival_time,
                                    "miles": f.miles,
                                    "is_direct": f.is_direct,
                                    "stops": f.stops,
                                    "booking_url": f.booking_url,
                                }
                                for f in flights
                            ]
                        else:
                            print("sem voos")

                await browser.close()
        except Exception as e:
            print(f"\nErro ao conectar ao Chrome: {e}")
        finally:
            proc.terminate()

    # Salva cache
    payload = {
        "harvested_at": datetime.now(timezone.utc).isoformat(),
        "flights": cache_entries,
    }
    CACHE_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    # Resumo
    print()
    print(f"Buscas concluídas. {len(all_flights)} voos encontrados no total.")
    if all_flights:
        print()
        print("Melhores ofertas:")
        sorted_flights = sorted(all_flights, key=lambda f: f.miles)
        for f in sorted_flights[:5]:
            direct = "direto" if f.is_direct else f"{f.stops} escala(s)"
            print(f"  {f.origin}→{f.destination} {f.departure_date} "
                  f"{f.departure_time}-{f.arrival_time} | {f.miles:,} milhas | {direct}")
    print()
    print(f"Cache salvo em: {CACHE_FILE}")
    print("O bot usará esses resultados. Válidos por ~2h.")


asyncio.run(main())
