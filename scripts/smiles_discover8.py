"""
Script de descoberta v8 — usa a x-api-key encontrada para chamar a API de busca de voos.
"""
import asyncio
import json
import urllib.request
from pathlib import Path
from playwright.async_api import async_playwright

ORIGIN = "CNF"
DEST = "IGU"
DATE = "2026-07-15"
API_KEY = "aJqPU7xNHl9qN3NVZnPaJ208aPo2Bh2p2ZV844tw"

def try_direct_api():
    """Tenta chamar a API diretamente com a x-api-key"""
    base_url = "https://flightavailability-prd.smiles.com.br"

    # Known endpoints from historical data
    endpoints = [
        f"/searchflights?adults=1&cabinType=all&children=0&currencyCode=BRL&departureDate={DATE}&destinationAirportCode={DEST}&infants=0&originAirportCode={ORIGIN}&tripType=2",
        f"/availabilities?adults=1&cabinType=all&children=0&currencyCode=BRL&departureDate={DATE}&destinationAirportCode={DEST}&infants=0&originAirportCode={ORIGIN}&tripType=2",
    ]

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "Origin": "https://www.smiles.com.br",
        "Referer": "https://www.smiles.com.br/",
        "x-api-key": API_KEY,
        "region": "BRAZIL",
        "channel": "WEB",
    }

    for ep in endpoints:
        url = base_url + ep
        print(f"\nTentando: {url[:100]}")
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read().decode('utf-8')
                print(f"Status: {resp.status}")
                parsed = json.loads(data)
                if isinstance(parsed, dict):
                    print(f"Keys: {list(parsed.keys())}")
                    # Save if it has flight data
                    if any(k in str(parsed.keys()).lower() for k in ['flight', 'segment', 'availability']):
                        Path("scripts").mkdir(exist_ok=True)
                        Path("scripts/smiles_flight_response.json").write_text(
                            json.dumps(parsed, indent=2, ensure_ascii=False)
                        )
                        print("SALVO em scripts/smiles_flight_response.json!")
                print(f"Body preview: {data[:500]}")
        except Exception as e:
            print(f"Error: {type(e).__name__}: {e}")


async def discover_via_playwright():
    """Usa Playwright para interceptar a chamada com todos os headers corretos"""
    all_flight_responses = []
    all_flight_requests = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        page = await context.new_page()

        async def capture_request(request):
            url = request.url
            if 'flightavailability' in url:
                headers = dict(request.headers)
                all_flight_requests.append({"url": url, "method": request.method, "headers": headers})
                print(f"[REQ] {request.method} {url[:120]}")

        async def capture_response(response):
            url = response.url
            status = response.status
            ct = response.headers.get("content-type", "")

            if 'flightavailability' in url:
                print(f"[RESP {status}] {url[:120]}")
                try:
                    if "json" in ct:
                        data = await response.json()
                        all_flight_responses.append({"url": url, "status": status, "data": data})
                        if isinstance(data, dict):
                            print(f"  Keys: {list(data.keys())}")
                except Exception as e:
                    print(f"  Error: {e}")

        page.on("request", capture_request)
        page.on("response", capture_response)

        # Intercept the flight/category request and then try to trigger a search
        url = f"https://www.smiles.com.br/passagens-aereas?originAirportCode={ORIGIN}&destinationAirportCode={DEST}&departureDate=15/07/2026&adults=1&tripType=2&cabinType=all"
        await page.goto(url, timeout=30000)
        await asyncio.sleep(5)

        # Try to execute a fetch using the captured API key
        print("\nTentando fetch direto via evaluate...")
        try:
            result = await page.evaluate(f"""
                async () => {{
                    try {{
                        const response = await fetch(
                            'https://flightavailability-prd.smiles.com.br/searchflights?adults=1&cabinType=all&children=0&currencyCode=BRL&departureDate=2026-07-15&destinationAirportCode=IGU&infants=0&originAirportCode=CNF&tripType=2',
                            {{
                                headers: {{
                                    'x-api-key': '{API_KEY}',
                                    'region': 'BRAZIL',
                                    'channel': 'WEB',
                                    'Accept': 'application/json',
                                }}
                            }}
                        );
                        const text = await response.text();
                        return {{ status: response.status, body: text.substring(0, 2000) }};
                    }} catch(e) {{
                        return {{ error: e.toString() }};
                    }}
                }}
            """)
            print(f"Result: {json.dumps(result, indent=2)[:1000]}")
        except Exception as e:
            print(f"Evaluate error: {e}")

        await asyncio.sleep(5)

        Path("scripts").mkdir(exist_ok=True)
        Path("scripts/smiles_discover8.json").write_text(
            json.dumps({
                "responses": all_flight_responses,
                "requests": all_flight_requests
            }, indent=2, ensure_ascii=False)
        )
        print(f"\n{len(all_flight_responses)} flight API responses")
        print(f"{len(all_flight_requests)} flight API requests")

        await browser.close()


if __name__ == "__main__":
    print("=== Testando API direta com x-api-key ===")
    try_direct_api()

    print("\n=== Tentando via Playwright ===")
    asyncio.run(discover_via_playwright())
