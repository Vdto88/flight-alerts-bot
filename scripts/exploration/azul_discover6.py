"""
Click a CNF->IGU 'Reserve agora' button and capture what happens.
Also try the top booking form with 'Reserve com Pontos' mode to find real inventory API.
"""
import asyncio
import json
import sys
import io
from pathlib import Path
from playwright.async_api import async_playwright

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

async def discover():
    captured = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=300)
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
            # Log non-tracker non-200 for booking-related domains
            if response.status not in (200, 204, 301, 302, 202):
                u = response.url
                if any(x in u for x in ['voeazul', 'azul', 'airtrfx']):
                    if 'analytics' not in u and 'taboola' not in u:
                        print(f"  [{response.status}] {u[:120]}")

        page.on("response", capture)

        print("=== PHASE 1: Try clicking Reserve agora on CNF->IGU fare ===")
        await page.goto("https://passagens.voeazul.com.br/br/pt/home",
                        timeout=60000, wait_until="domcontentloaded")
        await asyncio.sleep(5)

        try:
            await page.click('text=Aceitar', timeout=3000)
            await asyncio.sleep(1)
        except Exception:
            pass

        # Fill points form CNF -> IGU
        origin_sel = '#sfm-origin-64de11b8eb1aef385f06977a-input'
        await page.click(origin_sel)
        await asyncio.sleep(0.5)
        await page.fill(origin_sel, 'CNF')
        await asyncio.sleep(2)
        options = page.locator('[role="option"]')
        if await options.count() > 0:
            await options.first.click()
        await asyncio.sleep(1)

        dest_sel = '#sfm-destination-64de11b8eb1aef385f06977a-input'
        await page.click(dest_sel)
        await asyncio.sleep(0.5)
        await page.fill(dest_sel, 'IGU')
        await asyncio.sleep(2)
        options = page.locator('[role="option"]')
        if await options.count() > 0:
            await options.first.click()
        await asyncio.sleep(5)

        # Scroll to find CNF->IGU buttons
        await page.evaluate("window.scrollBy(0, 1500)")
        await asyncio.sleep(1)

        btns = page.locator('button[aria-label*="CNF"][aria-label*="IGU"]')
        btn_count = await btns.count()
        print(f"Found {btn_count} CNF->IGU buttons")

        if btn_count > 0:
            btn = btns.first
            # Scroll to it
            await btn.scroll_into_view_if_needed()
            await asyncio.sleep(1)
            label = await btn.get_attribute('aria-label')
            print(f"Clicking: {label[:80]}")
            await btn.click()
            await asyncio.sleep(5)
            print(f"URL after click: {page.url}")
            await page.screenshot(path="scripts/azul_after_click.png")
        else:
            print("No CNF->IGU buttons visible")

        # Save phase 1 responses
        phase1_captured = len(captured)

        print("\n=== PHASE 2: Try top booking form with 'Reserve com Pontos' mode ===")
        # The top booking form has a "Reserve com Reais" button that might switch to miles mode
        try:
            miles_toggle = page.locator('#headlessui-listbox-button-6')
            label = await miles_toggle.text_content()
            print(f"Current mode button text: {label}")
            await miles_toggle.click()
            await asyncio.sleep(1)
            # Look for "Reserve com Pontos" option
            pontos_option = page.get_by_text("Reserve com Pontos")
            count = await pontos_option.count()
            print(f"'Reserve com Pontos' options: {count}")
            if count > 0:
                await pontos_option.click()
                await asyncio.sleep(1)
                print("Switched to points mode")
        except Exception as e:
            print(f"Could not switch to points mode: {e}")

        # Now fill the top booking form
        print("Filling top booking form (CNF -> IGU)...")
        try:
            origin_top = page.locator('#cross-sell-search-panel-id-1-input')
            await origin_top.click()
            await asyncio.sleep(0.5)
            await origin_top.fill('CNF')
            await asyncio.sleep(2)
            options = page.locator('[role="option"]')
            if await options.count() > 0:
                await options.first.click()
            await asyncio.sleep(1)

            dest_top = page.locator('#cross-sell-search-panel-id-2-input')
            await dest_top.click()
            await asyncio.sleep(0.5)
            await dest_top.fill('IGU')
            await asyncio.sleep(2)
            options = page.locator('[role="option"]')
            if await options.count() > 0:
                await options.first.click()
            await asyncio.sleep(1)

            # Find and click submit/search button for top form
            # Usually it's "Buscar" or a search icon button
            search_btns = await page.evaluate("""
                () => {
                    const btns = document.querySelectorAll('button[type="submit"], button[aria-label*="earch"], button[aria-label*="uscar"]');
                    return Array.from(btns).slice(0, 5).map(b => ({
                        text: b.innerText.substring(0, 40),
                        ariaLabel: b.getAttribute('aria-label') || '',
                        id: b.id
                    }));
                }
            """)
            print("Search buttons near top form:")
            for b in search_btns:
                print(f"  '{b['text']}' aria='{b['ariaLabel']}'")

            # Try clicking the search button in top booking form
            # It might be inside the form container
            submit = page.locator('form button[type="submit"]').first
            if await submit.count() > 0:
                print("Clicking form submit button...")
                await submit.click()
                await asyncio.sleep(8)
                print(f"URL after submit: {page.url}")
            else:
                # Try "Buscar" text
                buscar = page.get_by_role("button", name="Buscar")
                if await buscar.count() > 0:
                    await buscar.click()
                    await asyncio.sleep(8)
                    print(f"URL after Buscar: {page.url}")
                else:
                    print("No submit button found in top form")
        except Exception as e:
            print(f"Top form error: {e}")

        await page.screenshot(path="scripts/azul_final.png")
        print(f"Final URL: {page.url}")

        scripts_dir = Path(__file__).parent
        out_path = scripts_dir / "azul_responses6.json"
        out_path.write_text(
            json.dumps(captured, indent=2, ensure_ascii=False),
            encoding='utf-8'
        )
        print(f"\n{len(captured)} total JSON responses saved to {out_path}")
        print(f"Phase 2 captured: {len(captured) - phase1_captured} new responses")

        # Print any new API endpoints from phase 2
        print("\n=== New endpoints from phase 2 ===")
        known = {'dpm.demdex.net', 'c.go-mpulse.net', 'fc-services-api.airtrfx.com',
                 'em-font-service-prod', 'azullinhasaereas.tt.omtrdc', 'em-prod-admin-worker',
                 'openair-california.airtrfx.com', 'vg-api.airtrfx.com', 'ct.pinterest',
                 'em-tr4ck-settings', 'mnrdszbvg02tmmt0gzqtcytdmm', 'us.creativecdn',
                 'mug.criteo', 'google-analytics', 'analytics.google', 'trc.taboola',
                 'trc-events.taboola', 'doubleclick', 'criteo', 'gum.criteo',
                 'salesforce.com'}
        for r in captured[phase1_captured:]:
            url = r['url']
            if not any(k in url for k in known):
                print(f"  NEW: {url[:120]}")

        await asyncio.sleep(15)
        await browser.close()

asyncio.run(discover())
