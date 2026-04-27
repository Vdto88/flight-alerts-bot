"""
Discovers Azul Fidelidade award flight search API.
Opens browser VISIBLE. Saves all JSON responses to scripts/azul_responses.json.
"""
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

async def discover():
    captured = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=200)
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
                        print(f"[JSON] {response.url[:120]}")
                    except Exception:
                        pass

        page.on("response", capture)

        # Navigate to Azul home page
        print("Navigating to passagens.voeazul.com.br/br/pt/home ...")
        await page.goto("https://passagens.voeazul.com.br/br/pt/home",
                        timeout=60000, wait_until="domcontentloaded")
        print("Page loaded (domcontentloaded). Waiting 5s for JS...")
        await asyncio.sleep(5)

        # Dump form elements to find selectors
        elements = await page.evaluate("""
            () => {
                const els = document.querySelectorAll('input, button[type="submit"], [data-testid], [aria-label]');
                return Array.from(els).slice(0, 80).map(el => ({
                    tag: el.tagName,
                    type: el.type || '',
                    id: el.id || '',
                    name: el.name || '',
                    placeholder: el.placeholder || '',
                    ariaLabel: el.getAttribute('aria-label') || '',
                    dataTestId: el.getAttribute('data-testid') || '',
                    text: el.innerText ? el.innerText.substring(0, 50) : ''
                }));
            }
        """)
        print("\n=== FORM ELEMENTS ===")
        for el in elements:
            if any([el['placeholder'], el['ariaLabel'], el['dataTestId'], el['id'], el['name']]):
                print(json.dumps(el))

        print("\nBrowser open for 120s.")
        print("Please manually navigate to the 'Viaje com Pontos' section,")
        print("fill in CNF -> IGU with a future date, and click search.")
        await asyncio.sleep(120)

        scripts_dir = Path(__file__).parent
        scripts_dir.mkdir(exist_ok=True)
        (scripts_dir / "azul_responses.json").write_text(
            json.dumps(captured, indent=2, ensure_ascii=False)
        )
        print(f"\n{len(captured)} JSON responses saved to scripts/azul_responses.json")
        await browser.close()

asyncio.run(discover())
