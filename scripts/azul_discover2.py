"""
Discovers Azul Fidelidade award flight search API by programmatically
filling in the "Viaje com Pontos" form on passagens.voeazul.com.br.
"""
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

async def discover():
    captured = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=500)
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
            elif response.status != 200:
                url = response.url
                # Only log non-tracker URLs
                if "airtrfx" in url or "voeazul" in url or "azul" in url.lower():
                    print(f"[{response.status}] {url[:120]}")

        page.on("response", capture)

        print("Loading home page...")
        await page.goto("https://passagens.voeazul.com.br/br/pt/home",
                        timeout=60000, wait_until="domcontentloaded")
        await asyncio.sleep(5)

        # Accept cookies if present
        try:
            await page.click('text=Aceitar', timeout=3000)
            print("Accepted cookies")
            await asyncio.sleep(1)
        except Exception:
            print("No cookie banner (or already accepted)")

        # The "Viaje com Pontos" form origin input
        # ID: sfm-origin-64de11b8eb1aef385f06977a-input
        print("\nFilling 'Viaje com Pontos' form...")
        origin_input = page.locator('#sfm-origin-64de11b8eb1aef385f06977a-input')

        await origin_input.click()
        await asyncio.sleep(1)
        await origin_input.fill("CNF")
        await asyncio.sleep(2)

        # Try clicking the first autocomplete suggestion
        try:
            await page.click('text=CNF', timeout=5000)
            print("Selected CNF")
        except Exception:
            print("Could not click CNF suggestion, trying other approach")
            # Try pressing Enter or Tab
            await page.keyboard.press("Enter")
        await asyncio.sleep(1)

        # Destination input
        dest_input = page.locator('#sfm-destination-64de11b8eb1aef385f06977a-input')
        await dest_input.click()
        await asyncio.sleep(1)
        await dest_input.fill("IGU")
        await asyncio.sleep(2)

        try:
            await page.click('text=IGU', timeout=5000)
            print("Selected IGU")
        except Exception:
            print("Could not click IGU suggestion")
            await page.keyboard.press("Enter")
        await asyncio.sleep(1)

        print("Waiting for results / API calls...")
        await asyncio.sleep(10)

        # Take a screenshot to see where we are
        await page.screenshot(path="scripts/azul_state.png")
        print("Screenshot saved to scripts/azul_state.png")

        print("\nBrowser open for 90s more. Try manually searching if form didn't auto-submit.")
        await asyncio.sleep(90)

        scripts_dir = Path(__file__).parent
        (scripts_dir / "azul_responses2.json").write_text(
            json.dumps(captured, indent=2, ensure_ascii=False)
        )
        print(f"\n{len(captured)} JSON responses saved to scripts/azul_responses2.json")
        await browser.close()

asyncio.run(discover())
