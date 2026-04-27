"""
Le dados diretamente do cache do Service Worker.
O browser armazenou respostas anteriores da API no Cache API.
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

        # Aguardar um pouco para o SW se registrar
        await asyncio.sleep(5)

        # Listar todos os caches do Service Worker
        print("\nListando caches do Service Worker...")
        cache_names = await page.evaluate("""
            async () => {
                try {
                    const names = await caches.keys();
                    return names;
                } catch(e) {
                    return ['error: ' + e.message];
                }
            }
        """)
        print(f"Caches encontrados: {cache_names}")

        # Listar todas as URLs em cada cache
        all_cached_urls = []
        for cache_name in (cache_names or []):
            if cache_name.startswith('error:'):
                continue
            urls = await page.evaluate(f"""
                async () => {{
                    try {{
                        const cache = await caches.open({json.dumps(cache_name)});
                        const keys = await cache.keys();
                        return keys.map(r => r.url);
                    }} catch(e) {{
                        return ['error: ' + e.message];
                    }}
                }}
            """)
            print(f"\nCache '{cache_name}': {len(urls)} entradas")
            for u in urls:
                if "airlines" in u or "flight" in u or "smiles" in u.lower():
                    print(f"  >> {u[:120]}")
                    all_cached_urls.append((cache_name, u))

        # Tentar ler dados de voos dos caches
        flight_data = None
        for cache_name, cached_url in all_cached_urls:
            if "airlines/search" in cached_url or "flightavail" in cached_url:
                print(f"\nLendo cache: {cached_url[:100]}")
                result = await page.evaluate(f"""
                    async () => {{
                        try {{
                            const cache = await caches.open({json.dumps(cache_name)});
                            const response = await cache.match({json.dumps(cached_url)});
                            if (!response) return {{error: 'not found'}};
                            const text = await response.text();
                            return {{status: response.status, body: text.substring(0, 50000)}};
                        }} catch(e) {{
                            return {{error: e.message}};
                        }}
                    }}
                """)
                print(f"  status={result.get('status')}, body_len={len(result.get('body',''))}")
                if result.get('status') == 200 and result.get('body'):
                    try:
                        data = json.loads(result['body'])
                        flight_data = data
                        print(f"  >>> DADOS DO CACHE! Keys: {list(data.keys())[:6]}")
                    except Exception as e:
                        print(f"  Erro JSON: {e}")

        await page.screenshot(path="scripts/sw_cache_screenshot.png", full_page=False)

        # Tentar ler IndexedDB tambem
        print("\n\nVerificando IndexedDB...")
        idb_data = await page.evaluate("""
            async () => {
                return new Promise((resolve) => {
                    const databases = indexedDB.databases ? indexedDB.databases() : Promise.resolve([]);
                    Promise.resolve(databases).then(dbs => {
                        resolve(dbs.map(d => d.name + '@' + d.version));
                    }).catch(() => resolve([]));
                });
            }
        """)
        print(f"IndexedDB: {idb_data}")

        await browser.close()

    if flight_data:
        out = Path("scripts/sw_cache_result.json")
        out.write_text(json.dumps(flight_data, indent=2, ensure_ascii=False))
        print(f"\nDados salvos em: {out}")
        if "requestedFlightSegmentList" in flight_data:
            segs = flight_data["requestedFlightSegmentList"]
            total = sum(len(s.get("flightList", [])) for s in segs)
            print(f"VOOS: {total}")
    else:
        print("\nNenhum dado de voos no cache.")


asyncio.run(main())
