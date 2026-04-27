"""
Discovers Azul Fidelidade award flight search API by clicking the search button
on the 'Viaje com Pontos' form and capturing what XHRs fire.
"""
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

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
                        captured.append({"url": url, "data": data, "status": response.status})
                        print(f"[JSON 200] {url[:120]}")
                    except Exception:
                        pass
            # Also log non-tracker non-200 for airtrfx/voeazul
            if response.status not in (200, 204, 301, 302, 204):
                if "airtrfx" in url or "voeazul" in url or ("azul" in url.lower() and "analytics" not in url):
                    print(f"[{response.status}] {url[:120]}")

        page.on("response", capture)

        print("Loading page...")
        await page.goto("https://passagens.voeazul.com.br/br/pt/home",
                        timeout=60000, wait_until="domcontentloaded")
        await asyncio.sleep(5)

        # Accept cookies
        try:
            await page.click('text=Aceitar', timeout=3000)
            print("Accepted cookies")
            await asyncio.sleep(1)
        except Exception:
            pass

        # Fill origin in "Viaje com Pontos" form
        # ID: sfm-origin-64de11b8eb1aef385f06977a-input
        print("\nFilling Viaje com Pontos origin = CNF...")
        origin_sel = '#sfm-origin-64de11b8eb1aef385f06977a-input'
        await page.click(origin_sel)
        await asyncio.sleep(0.5)
        await page.fill(origin_sel, 'CNF')
        await asyncio.sleep(2)

        # Click first dropdown option
        try:
            # Look for autocomplete items
            options = page.locator('[role="option"]')
            count = await options.count()
            print(f"Found {count} autocomplete options")
            if count > 0:
                first_text = await options.first.text_content()
                print(f"Clicking: {first_text}")
                await options.first.click()
            else:
                # Try pressing enter or selecting from list
                await page.keyboard.press('Enter')
        except Exception as e:
            print(f"Autocomplete error: {e}")
            await page.keyboard.press('Escape')
        await asyncio.sleep(1)

        # Fill destination
        print("Filling destination = IGU...")
        dest_sel = '#sfm-destination-64de11b8eb1aef385f06977a-input'
        await page.click(dest_sel)
        await asyncio.sleep(0.5)
        await page.fill(dest_sel, 'IGU')
        await asyncio.sleep(2)

        try:
            options = page.locator('[role="option"]')
            count = await options.count()
            print(f"Found {count} autocomplete options")
            if count > 0:
                first_text = await options.first.text_content()
                print(f"Clicking: {first_text}")
                await options.first.click()
            else:
                await page.keyboard.press('Enter')
        except Exception as e:
            print(f"Autocomplete error: {e}")
        await asyncio.sleep(1)

        # Take screenshot to see current state
        await page.screenshot(path="scripts/azul_form_filled.png")
        print("Screenshot: scripts/azul_form_filled.png")

        # Now look for a search/submit button near the points form
        print("\nLooking for search button near points form...")
        # The form might have a submit button with text like "Buscar" or "Pesquisar"
        buttons = await page.evaluate("""
            () => {
                // Look for buttons in or near the pontos section
                const allButtons = document.querySelectorAll('button');
                return Array.from(allButtons).map(b => ({
                    text: b.innerText.trim().substring(0, 60),
                    ariaLabel: b.getAttribute('aria-label') || '',
                    classes: b.className.substring(0, 80),
                    id: b.id
                })).filter(b => b.text || b.ariaLabel);
            }
        """)
        print("All buttons:")
        for b in buttons:
            print(f"  '{b['text']}' | aria='{b['ariaLabel'][:50]}' | id='{b['id']}'")

        # Try clicking a search button
        # Common patterns: "Buscar", "Pesquisar", type="submit"
        clicked = False
        for btn_text in ["Buscar", "Pesquisar", "Search", "Buscar voos"]:
            try:
                btn = page.get_by_role("button", name=btn_text)
                if await btn.count() > 0:
                    print(f"Clicking button: '{btn_text}'")
                    await btn.click()
                    clicked = True
                    break
            except Exception:
                pass

        if not clicked:
            print("\nNo standard search button found. Waiting 120s for manual interaction.")
            print("Please click the search/submit button near the 'Viaje com Pontos' section.")

        # Wait for navigation/API calls
        await asyncio.sleep(10)
        print(f"\nCurrent URL: {page.url}")
        await page.screenshot(path="scripts/azul_after_search.png")
        print("Screenshot: scripts/azul_after_search.png")

        # Wait longer to see if navigation happens
        await asyncio.sleep(100)
        print(f"Final URL: {page.url}")

        scripts_dir = Path(__file__).parent
        (scripts_dir / "azul_responses3.json").write_text(
            json.dumps(captured, indent=2, ensure_ascii=False)
        )
        print(f"\n{len(captured)} JSON responses saved to scripts/azul_responses3.json")

        # Summarize what was captured after CNF was typed (post-initial load)
        print("\n=== New URLs after form interaction ===")
        known_initial = {
            'dpm.demdex.net', 'c.go-mpulse.net', 'fc-services-api.airtrfx.com',
            'em-font-service-prod', 'azullinhasaereas.tt.omtrdc', 'em-prod-admin-worker',
            'openair-california.airtrfx.com', 'vg-api.airtrfx.com', 'ct.pinterest',
            'em-tr4ck-settings', 'mnrdszbvg02tmmt0gzqtcytdmm', 'us.creativecdn',
            'mug.criteo', 'google-analytics', 'analytics.google', 'trc.taboola',
            'trc-events.taboola', 'doubleclick', 'criteo', 'gum.criteo',
        }
        for r in captured:
            url = r['url']
            if not any(k in url for k in known_initial):
                print(f"  NEW: {url[:120]}")

        await browser.close()

asyncio.run(discover())
