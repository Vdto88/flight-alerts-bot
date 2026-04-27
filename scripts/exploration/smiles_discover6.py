"""
Script de descoberta v6 — tenta URLs de SPA/MFE do Smiles e usa route navigation.
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
    flight_requests = []

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
            if 'flightavailability' in url or 'api-air' in url:
                print(f"[REQ] {request.method} {url[:150]}")
                flight_requests.append({
                    "url": url,
                    "method": request.method,
                    "headers": dict(request.headers)
                })

        async def capture_response(response):
            url = response.url
            status = response.status
            ct = response.headers.get("content-type", "")

            if 'flightavailability' in url or 'api-air' in url:
                print(f"[RESP {status}] {url[:150]}")
                try:
                    if "json" in ct:
                        data = await response.json()
                        all_responses.append({"url": url, "status": status, "data": data})
                    else:
                        body = await response.text()
                        all_responses.append({"url": url, "status": status, "body": body[:1000]})
                except Exception as e:
                    print(f"  Error: {e}")

        page.on("request", capture_request)
        page.on("response", capture_response)

        # Try to figure out the correct URL structure
        # The old URL: /emissao-passagem-com-milhas returns 404
        # The new URL: /passagens-aereas seems to be the search page
        # But maybe the MFE is at a different path

        urls = [
            # MFE-based search result page
            f"https://www.smiles.com.br/mfe-apps/booking/search-result?originAirportCode={ORIGIN}&destinationAirportCode={DEST}&departureDate={DATE}&adults=1&tripType=2",
            # Direct API endpoint
            f"https://flightavailability-prd.smiles.com.br/searchflights?adults=1&cabinType=all&children=0&currencyCode=BRL&departureDate=2026-07-15&destinationAirportCode={DEST}&infants=0&originAirportCode={ORIGIN}&tripType=2",
        ]

        for try_url in urls:
            print(f"\nTentando: {try_url[:100]}")
            try:
                resp = await page.goto(try_url, timeout=15000)
                print(f"Status da página: {resp.status if resp else 'None'}")
                await asyncio.sleep(3)
                # Get page title
                title = await page.title()
                print(f"Título: {title}")
            except Exception as e:
                print(f"Error: {e}")

        # Wait for more network activity
        print("\nAguardando mais respostas...")
        await asyncio.sleep(5)

        Path("scripts").mkdir(exist_ok=True)
        Path("scripts/smiles_discover6.json").write_text(
            json.dumps({
                "responses": all_responses,
                "flight_requests": flight_requests
            }, indent=2, ensure_ascii=False)
        )
        print(f"\n{len(all_responses)} respostas capturadas")
        print(f"{len(flight_requests)} flight API requests")

        await browser.close()

asyncio.run(discover())
