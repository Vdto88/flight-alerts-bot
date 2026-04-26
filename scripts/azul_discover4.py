"""
Discovers Azul Fidelidade award API - capture CNF->IGU graphql responses
and click a Reserve agora button to see the booking URL.
"""
import asyncio
import json
import sys
from pathlib import Path
from playwright.async_api import async_playwright

# Fix Windows encoding
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

async def discover():
    captured = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=400)
        page = await browser.new_page(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ))

        async def capture(response):
            url = response.url
            if response.status == 200:
                ct = response.headers.get("content-type", "")
                if "json" in ct:
                    try:
                        data = await response.json()
                        captured.append({"url": url, "data": data})
                        print(f"[JSON] {url[:120]}")
                    except Exception:
                        pass

        page.on("response", capture)

        print("Loading page...")
        await page.goto("https://passagens.voeazul.com.br/br/pt/home",
                        timeout=60000, wait_until="domcontentloaded")
        await asyncio.sleep(5)

        try:
            await page.click('text=Aceitar', timeout=3000)
            await asyncio.sleep(1)
        except Exception:
            pass

        # Fill origin CNF
        origin_sel = '#sfm-origin-64de11b8eb1aef385f06977a-input'
        await page.click(origin_sel)
        await asyncio.sleep(0.5)
        await page.fill(origin_sel, 'CNF')
        await asyncio.sleep(2)
        options = page.locator('[role="option"]')
        if await options.count() > 0:
            await options.first.click()
        else:
            await page.keyboard.press('Enter')
        await asyncio.sleep(1)

        # Fill destination IGU
        dest_sel = '#sfm-destination-64de11b8eb1aef385f06977a-input'
        await page.click(dest_sel)
        await asyncio.sleep(0.5)
        await page.fill(dest_sel, 'IGU')
        await asyncio.sleep(2)
        options = page.locator('[role="option"]')
        if await options.count() > 0:
            await options.first.click()
        else:
            await page.keyboard.press('Enter')
        await asyncio.sleep(3)

        print("Form filled. Waiting for graphql responses...")
        await asyncio.sleep(5)

        # Find and click a CNF->IGU Reserve agora button
        print("Looking for CNF->IGU Reserve agora button...")
        btns = page.locator('button[aria-label*="CNF"][aria-label*="IGU"]')
        btn_count = await btns.count()
        print(f"Found {btn_count} CNF->IGU buttons")

        booking_url = None
        if btn_count > 0:
            # Get the aria-label of first button to see date/points info
            first_label = await btns.first.get_attribute('aria-label')
            print(f"First button: {first_label}")

            # Open in new tab to capture the booking URL
            async with page.expect_popup() as popup_info:
                await btns.first.click(modifiers=["Control"])
            popup = await popup_info.value
            await asyncio.sleep(3)
            booking_url = popup.url
            print(f"Booking URL: {booking_url}")
            await popup.close()
        else:
            print("No CNF->IGU buttons found. Capturing what we have.")

        # Save all captured responses
        scripts_dir = Path(__file__).parent
        (scripts_dir / "azul_responses4.json").write_text(
            json.dumps(captured, indent=2, ensure_ascii=False),
            encoding='utf-8'
        )
        print(f"\n{len(captured)} JSON responses saved to scripts/azul_responses4.json")

        # Find graphql responses that have CNF in them
        print("\n=== GraphQL responses with CNF fares ===")
        for r in captured:
            if 'graphql' in r['url']:
                data = r['data']
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and 'data' in item:
                            for key, val in item['data'].items():
                                if isinstance(val, dict) and 'fares' in val:
                                    fares = val.get('fares', [])
                                    cnf_fares = [f for f in fares
                                                 if 'CNF' in (f.get('originAirportCode','') + f.get('destinationAirportCode',''))]
                                    if cnf_fares:
                                        print(f"Module {key}, {len(cnf_fares)} CNF fares:")
                                        for f in cnf_fares[:2]:
                                            print(json.dumps(f, indent=2, ensure_ascii=False))
                                        print("---")

        print("\nWaiting 30s before closing...")
        await asyncio.sleep(30)
        await browser.close()

asyncio.run(discover())
