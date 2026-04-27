"""
Script de descoberta v2 — captura TODOS os requests/respostas para encontrar a API de voos.
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
            all_requests.append({"url": request.url, "method": request.method})
            if "smiles" in request.url.lower() or "flight" in request.url.lower() or "milhas" in request.url.lower():
                print(f"[REQ] {request.method} {request.url[:120]}")

        async def capture_response(response):
            url = response.url
            status = response.status
            ct = response.headers.get("content-type", "")

            # Log all smiles/flight related requests
            if "smiles" in url.lower() or "flight" in url.lower():
                print(f"[RESP {status}] {url[:120]} content-type={ct[:50]}")

            if status == 200 and "json" in ct:
                try:
                    data = await response.json()
                    all_responses.append({"url": url, "status": status, "data": data})
                except Exception as e:
                    pass
            elif status != 200 and "smiles" in url.lower():
                try:
                    body = await response.text()
                    all_responses.append({"url": url, "status": status, "body": body[:500]})
                except Exception:
                    pass

        page.on("request", capture_request)
        page.on("response", capture_response)

        url = (
            f"https://www.smiles.com.br/emissao-passagem-com-milhas"
            f"?originAirportCode={ORIGIN}&destinationAirportCode={DEST}"
            f"&departureDate={DATE}&adults=1&children=0&infants=0"
            f"&tripType=2&cabinType=all"
        )
        print(f"Abrindo: {url}")
        await page.goto(url, timeout=60000)

        print("Aguardando networkidle...")
        try:
            await page.wait_for_load_state("networkidle", timeout=30000)
        except Exception as e:
            print(f"networkidle timeout: {e}")

        await asyncio.sleep(10)

        Path("scripts").mkdir(exist_ok=True)
        Path("scripts/smiles_responses2.json").write_text(
            json.dumps(all_responses, indent=2, ensure_ascii=False)
        )
        Path("scripts/smiles_requests.json").write_text(
            json.dumps(all_requests, indent=2, ensure_ascii=False)
        )
        print(f"\n{len(all_responses)} respostas salvas em scripts/smiles_responses2.json")
        print(f"{len(all_requests)} requests salvos em scripts/smiles_requests.json")

        await browser.close()

asyncio.run(discover())
