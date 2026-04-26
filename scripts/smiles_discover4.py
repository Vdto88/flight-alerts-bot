"""
Script de descoberta v4 — tenta fazer a chamada direta à API do Smiles
para descobrir a URL real da busca de voos.
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
        context = await browser.new_context(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ))
        page = await context.new_page()

        async def capture_request(request):
            url = request.url
            all_requests.append({"url": url, "method": request.method, "headers": dict(request.headers)})

        async def capture_response(response):
            url = response.url
            status = response.status
            ct = response.headers.get("content-type", "")

            if 'flightavailability' in url.lower():
                print(f"[FLIGHT {status}] {url[:150]}")
                try:
                    body = await response.text()
                    print(f"  Body preview: {body[:500]}")
                except:
                    pass

            if status == 200 and "json" in ct:
                try:
                    data = await response.json()
                    all_responses.append({"url": url, "status": status, "data": data})
                except Exception:
                    pass

        page.on("request", capture_request)
        page.on("response", capture_response)

        # Load the search page with parameters
        url = f"https://www.smiles.com.br/passagens-aereas?originAirportCode={ORIGIN}&destinationAirportCode={DEST}&departureDate={DATE}&adults=1&tripType=2&cabinType=all"
        print(f"Abrindo: {url}")
        await page.goto(url, timeout=30000)

        print("Aguardando 15 segundos...")
        await asyncio.sleep(15)

        # Try to find and click the search button if needed
        print("\nHTML do body (primeiros 3000 chars):")
        html = await page.content()
        print(html[:3000])

        Path("scripts").mkdir(exist_ok=True)
        Path("scripts/smiles_responses4.json").write_text(
            json.dumps(all_responses, indent=2, ensure_ascii=False)
        )
        Path("scripts/smiles_requests4.json").write_text(
            json.dumps(all_requests, indent=2, ensure_ascii=False)
        )
        print(f"\n{len(all_responses)} respostas JSON salvas")

        await browser.close()

asyncio.run(discover())
