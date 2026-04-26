"""
Script de descoberta v3 — tenta a URL nova do Smiles (angular/SPA).
Captura TODOS os requests de API de voos.
"""
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

ORIGIN = "CNF"
DEST = "IGU"
DATE = "15/07/2026"

async def discover():
    all_responses = []
    all_requests = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ))

        async def capture_request(request):
            url = request.url
            all_requests.append({"url": url, "method": request.method})

        async def capture_response(response):
            url = response.url
            status = response.status
            ct = response.headers.get("content-type", "")

            if status == 200 and "json" in ct:
                try:
                    data = await response.json()
                    all_responses.append({"url": url, "status": status, "data": data})
                    # Print key info for flight-related responses
                    if isinstance(data, dict):
                        keys = list(data.keys())
                        if any(k in str(keys).lower() for k in ['flight', 'segment', 'availability', 'miles', 'passagem']):
                            print(f"[FLIGHT JSON] {url[:100]}")
                            print(f"  Keys: {keys[:10]}")
                except Exception:
                    pass

        page.on("request", capture_request)
        page.on("response", capture_response)

        # Try both old and new URLs
        urls_to_try = [
            f"https://www.smiles.com.br/passagens-aereas?originAirportCode={ORIGIN}&destinationAirportCode={DEST}&departureDate={DATE}&adults=1&tripType=2",
            f"https://www.smiles.com.br/search?originAirportCode={ORIGIN}&destinationAirportCode={DEST}&departureDate={DATE}&adults=1&tripType=2",
        ]

        for try_url in urls_to_try:
            print(f"\nTentando: {try_url}")
            try:
                resp = await page.goto(try_url, timeout=20000)
                print(f"Status: {resp.status if resp else 'None'}")
                await asyncio.sleep(5)
            except Exception as e:
                print(f"Error: {e}")

        Path("scripts").mkdir(exist_ok=True)
        Path("scripts/smiles_responses3.json").write_text(
            json.dumps(all_responses, indent=2, ensure_ascii=False)
        )
        Path("scripts/smiles_requests3.json").write_text(
            json.dumps(all_requests, indent=2, ensure_ascii=False)
        )
        print(f"\n{len(all_responses)} respostas JSON salvas")
        print(f"{len(all_requests)} requests capturados")

        await browser.close()

asyncio.run(discover())
