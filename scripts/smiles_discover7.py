"""
Script de descoberta v7 — busca as chaves de API no código JavaScript do Smiles.
Também tenta clicar no botão de busca para acionar a chamada à API de voos.
"""
import asyncio
import json
import re
from pathlib import Path
from playwright.async_api import async_playwright

ORIGIN = "CNF"
DEST = "IGU"
DATE = "15/07/2026"

async def discover():
    all_responses = []
    all_requests_detail = []

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
                headers = dict(request.headers)
                all_requests_detail.append({
                    "url": url,
                    "method": request.method,
                    "headers": headers
                })
                print(f"[REQ] {request.method} {url[:100]}")
                for k, v in headers.items():
                    if k.lower() in ['x-api-key', 'authorization', 'region', 'channel', 'x-region', 'x-channel', 'x-authorization']:
                        print(f"  {k}: {v}")

        async def capture_response(response):
            url = response.url
            status = response.status
            ct = response.headers.get("content-type", "")

            if 'flightavailability' in url or 'api-air' in url:
                print(f"[RESP {status}] {url[:100]}")
                try:
                    if "json" in ct:
                        data = await response.json()
                        all_responses.append({"url": url, "status": status, "data": data})
                        if status == 200:
                            keys = list(data.keys()) if isinstance(data, dict) else "list"
                            print(f"  Keys: {keys}")
                    else:
                        body = await response.text()
                        all_responses.append({"url": url, "status": status, "body": body[:500]})
                except Exception as e:
                    print(f"  Error: {e}")

        page.on("request", capture_request)
        page.on("response", capture_response)

        # Load the search results page with URL parameters
        url = f"https://www.smiles.com.br/passagens-aereas?originAirportCode={ORIGIN}&destinationAirportCode={DEST}&departureDate={DATE}&adults=1&tripType=2&cabinType=all"
        print(f"Abrindo: {url}")
        await page.goto(url, timeout=30000)

        print("Aguardando carregamento inicial (10s)...")
        await asyncio.sleep(10)

        # Look for the search controller JS
        print("\nBuscando JS do SearchFlightController...")
        js_urls = []
        for req in all_requests_detail:
            pass  # already filtered to flight APIs

        # Try to find x-api-key in page JavaScript
        print("\nBuscando x-api-key no HTML/JS...")
        content = await page.content()
        api_keys = re.findall(r'x.api.key["\s:]+([A-Za-z0-9/+]{20,})', content, re.IGNORECASE)
        if api_keys:
            print(f"Found api keys: {api_keys}")
        else:
            print("Nenhuma x-api-key encontrada no HTML inicial")

        # Try to access the SearchFlightController.js
        js_url = "https://www.smiles.com.br/smiles-booking-portlet/js/search/SearchFlightController.js"
        print(f"\nCarregando: {js_url}")
        try:
            js_resp = await page.evaluate(f"""
                () => fetch('{js_url}').then(r => r.text())
            """)
            # Search for API keys/base URLs in the JS
            api_key_matches = re.findall(r'["\']([A-Za-z0-9]{30,60})["\']', js_resp[:5000])
            base_url_matches = re.findall(r'https://[a-z0-9\-\.]+smiles[a-z0-9\-\.]*\.com\.br[/a-z0-9\-]*', js_resp)
            print(f"API key candidates: {api_key_matches[:5]}")
            print(f"Base URLs found: {list(set(base_url_matches))[:10]}")
            Path("scripts/search_flight_controller.js").write_text(js_resp[:50000])
        except Exception as e:
            print(f"Error loading JS: {e}")

        # Try to click the search button on the page
        print("\nBuscando botão de busca...")
        try:
            # Look for the search form and try to submit it
            buttons = await page.query_selector_all("button[type='submit'], .btn-buscar, .search-button, input[type='submit']")
            print(f"Found {len(buttons)} submit buttons")

            for btn in buttons[:3]:
                text = await btn.text_content()
                print(f"  Button: '{text}'")
        except Exception as e:
            print(f"Error finding buttons: {e}")

        # Wait longer for any API calls
        await asyncio.sleep(5)

        Path("scripts").mkdir(exist_ok=True)
        Path("scripts/smiles_discover7.json").write_text(
            json.dumps({
                "responses": all_responses,
                "requests": all_requests_detail
            }, indent=2, ensure_ascii=False)
        )
        print(f"\n{len(all_responses)} respostas de flight API capturadas")
        print(f"{len(all_requests_detail)} requests de flight API")

        await browser.close()

asyncio.run(discover())
