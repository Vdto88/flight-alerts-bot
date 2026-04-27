"""
Script de descoberta v5 — tenta a API direta do flightavailability.
Também carrega a página e aguarda os resultados aparecerem.
"""
import asyncio
import json
import urllib.request
from pathlib import Path
from playwright.async_api import async_playwright

ORIGIN = "CNF"
DEST = "IGU"
DATE = "15/07/2026"

async def try_direct_api():
    """Tenta chamar a API diretamente sem autenticação"""
    base_url = "https://flightavailability-prd.smiles.com.br"
    endpoints = [
        f"/searchflights?adults=1&cabinType=all&children=0&currencyCode=BRL&departureDate=2026-07-15&destinationAirportCode=IGU&infants=0&originAirportCode=CNF&tripType=2",
        f"/availabilities?adults=1&cabinType=all&children=0&currencyCode=BRL&departureDate=2026-07-15&destinationAirportCode=IGU&infants=0&originAirportCode=CNF&tripType=2",
        f"/flights?adults=1&cabinType=all&children=0&currencyCode=BRL&departureDate=2026-07-15&destinationAirportCode=IGU&infants=0&originAirportCode=CNF",
    ]

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
        "Origin": "https://www.smiles.com.br",
        "Referer": "https://www.smiles.com.br/",
    }

    for ep in endpoints:
        url = base_url + ep
        print(f"\nTentando: {url[:100]}")
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = resp.read().decode('utf-8')
                print(f"Status: {resp.status}")
                print(f"Body: {data[:500]}")
        except Exception as e:
            print(f"Error: {e}")


async def discover_with_playwright():
    all_responses = []
    all_requests_detail = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        async def capture_request(request):
            url = request.url
            if 'flightavailability' in url or 'smiles' in url.lower():
                all_requests_detail.append({
                    "url": url,
                    "method": request.method,
                    "headers": {k: v for k, v in request.headers.items() if k.lower() in ['x-api-key', 'authorization', 'x-authorization', 'region', 'channel', 'content-type', 'accept']}
                })

        async def capture_response(response):
            url = response.url
            status = response.status
            ct = response.headers.get("content-type", "")

            if 'flightavailability' in url:
                print(f"[FLIGHT-API {status}] {url[:150]}")
                try:
                    body = await response.text()
                    print(f"  Preview: {body[:300]}")
                    all_responses.append({"url": url, "status": status, "body": body[:2000]})
                except:
                    pass

        page.on("request", capture_request)
        page.on("response", capture_response)

        # Try the search result page directly
        url = f"https://www.smiles.com.br/passagens-aereas?originAirportCode={ORIGIN}&destinationAirportCode={DEST}&departureDate={DATE}&adults=1&tripType=2&cabinType=all"
        print(f"\nAbrindo: {url}")
        await page.goto(url, timeout=30000)

        print("Aguardando 20 segundos para carregamento total...")
        await asyncio.sleep(20)

        # Check if there's any content about flights in the page
        content = await page.content()
        if 'CNF' in content or 'IGU' in content:
            print("Página contém dados de CNF/IGU")
        else:
            print("AVISO: Página não contém dados de CNF/IGU")

        # Save detailed request info
        Path("scripts").mkdir(exist_ok=True)
        Path("scripts/smiles_discover5.json").write_text(
            json.dumps({
                "responses": all_responses,
                "requests": all_requests_detail
            }, indent=2, ensure_ascii=False)
        )
        print(f"\n{len(all_responses)} respostas de flightavailability")
        print(f"{len(all_requests_detail)} requests para smiles")

        await browser.close()


if __name__ == "__main__":
    print("=== Testando API direta ===")
    asyncio.run(try_direct_api())

    print("\n=== Tentando Playwright ===")
    asyncio.run(discover_with_playwright())
