"""
Script de descoberta — executa uma vez para capturar o JSON real da API do Smiles.
Salva todas as respostas JSON em scripts/smiles_responses.json.
"""
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

ORIGIN = "CNF"
DEST = "IGU"
DATE = "15/07/2026"

async def discover():
    captured = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)  # headless for CI/agent
        page = await browser.new_page(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ))

        async def capture(response):
            if response.status == 200:
                ct = response.headers.get("content-type", "")
                if "json" in ct:
                    try:
                        data = await response.json()
                        captured.append({"url": response.url, "data": data})
                        print(f"[JSON] {response.url}")
                    except Exception:
                        pass

        page.on("response", capture)

        url = (
            f"https://www.smiles.com.br/emissao-passagem-com-milhas"
            f"?originAirportCode={ORIGIN}&destinationAirportCode={DEST}"
            f"&departureDate={DATE}&adults=1&children=0&infants=0"
            f"&tripType=2&cabinType=all"
        )
        print(f"Abrindo: {url}")
        await page.goto(url, timeout=30000)
        await asyncio.sleep(12)  # aguardar carregamento completo

        Path("scripts").mkdir(exist_ok=True)
        Path("scripts/smiles_responses.json").write_text(
            json.dumps(captured, indent=2, ensure_ascii=False)
        )
        print(f"\n{len(captured)} respostas JSON salvas em scripts/smiles_responses.json")

        await browser.close()

asyncio.run(discover())
