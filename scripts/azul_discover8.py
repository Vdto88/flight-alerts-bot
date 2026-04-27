"""
Try to use the main Azul booking form (not the deals widget) and find the real flight search.
Focus on: top booking panel "Passagens Aereas" > "Reserve com Pontos" mode.
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
    captured_urls = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=300)
        context = await browser.new_context(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ))
        page = await context.new_page()

        async def capture(response):
            url = response.url
            if url in captured_urls:
                return
            if response.status == 200:
                ct = response.headers.get("content-type", "")
                if "json" in ct:
                    try:
                        data = await response.json()
                        captured.append({"url": url, "data": data})
                        captured_urls.add(url)
                        # Only print non-tracker responses
                        if any(x in url for x in ['airtrfx', 'voeazul', 'azul']) and 'analytics' not in url:
                            print(f"[JSON] {url[:120]}")
                    except Exception:
                        pass
            # Log any non-200 azul/airtrfx responses
            if response.status not in (200, 204, 301, 302, 202):
                u = response.url
                if any(x in u for x in ['voeazul', 'azul.com', 'airtrfx']) and 'analytics' not in u:
                    print(f"  [{response.status}] {u[:120]}")

        page.on("response", capture)

        # Go to the page
        await page.goto("https://passagens.voeazul.com.br/br/pt/home",
                        timeout=60000, wait_until="domcontentloaded")
        await asyncio.sleep(6)

        try:
            await page.click('text=Aceitar', timeout=3000)
            await asyncio.sleep(1)
        except Exception:
            pass

        # Switch top form to "Reserve com Pontos" mode
        print("Switching top form to Reserve com Pontos...")
        mode_btn = page.locator('#headlessui-listbox-button-6')
        await mode_btn.click()
        await asyncio.sleep(1.5)
        pontos_opt = page.get_by_role('option', name='Reserve com Pontos', exact=False)
        await pontos_opt.click()
        await asyncio.sleep(2)
        print(f"Mode switched. Current mode btn text: {await mode_btn.text_content()}")

        # Fill origin
        print("Filling CNF...")
        await page.click('#cross-sell-search-panel-id-1-input')
        await asyncio.sleep(0.5)
        await page.fill('#cross-sell-search-panel-id-1-input', 'CNF')
        await asyncio.sleep(2)
        options = page.locator('[role="option"]')
        count = await options.count()
        if count > 0:
            t = await options.first.text_content()
            print(f"Selecting: {t}")
            await options.first.click()
        await asyncio.sleep(1)

        # Fill destination
        print("Filling IGU...")
        await page.click('#cross-sell-search-panel-id-2-input')
        await asyncio.sleep(0.5)
        await page.fill('#cross-sell-search-panel-id-2-input', 'IGU')
        await asyncio.sleep(2)
        options = page.locator('[role="option"]')
        count = await options.count()
        if count > 0:
            t = await options.first.text_content()
            print(f"Selecting: {t}")
            await options.first.click()
        await asyncio.sleep(1)

        # Now find the date field and submit button
        date_info = await page.evaluate("""
            () => {
                // Find date input fields
                const dateInputs = document.querySelectorAll('input[type="date"], input[placeholder*="data"], input[placeholder*="Data"], [id*="date"]');
                return Array.from(dateInputs).slice(0, 5).map(el => ({
                    id: el.id,
                    type: el.type,
                    placeholder: el.placeholder || ''
                }));
            }
        """)
        print("Date fields:", date_info)

        # Look for the date trigger button
        date_trigger = page.locator('#date-input-12-trigger')
        if await date_trigger.count() > 0:
            print("Clicking date trigger...")
            await date_trigger.click()
            await asyncio.sleep(2)
            # Take screenshot to see the date picker
            await page.screenshot(path="scripts/azul_date_picker.png")
            print("Screenshot: azul_date_picker.png")
            # Press escape to close date picker
            await page.keyboard.press('Escape')
            await asyncio.sleep(1)

        # Find the Buscar/Search button for top booking form
        form_btns = await page.evaluate("""
            () => {
                // Look for a button that is inside or near the booking form
                // It's usually the last button or has class like "search" or text "Buscar"
                const allBtns = document.querySelectorAll('button');
                return Array.from(allBtns).filter(b => {
                    const txt = b.innerText.trim();
                    return txt.includes('Buscar') || txt.includes('Pesquisa') ||
                           txt === 'search' || b.type === 'submit';
                }).map(b => ({
                    text: b.innerText.trim().substring(0, 60),
                    ariaLabel: b.getAttribute('aria-label') || '',
                    id: b.id,
                    type: b.type
                }));
            }
        """)
        print(f"Search buttons: {form_btns}")

        # The main Azul booking form submits to a results page
        # Try using voeazul.com.br directly which may have better URL structure
        print("\n=== Testing direct URL navigation for awards ===")
        # Known award search URL patterns
        test_urls = [
            "https://passagens.voeazul.com.br/br/pt/search-result#adults=1&children=0&infants=0&journeyType=ONE_WAY&origin=CNF&destination=IGU&departureDate=2026-07-15&redemption=true",
            "https://passagens.voeazul.com.br/br/pt/search-result#adults=1&journeyType=ONE_WAY&origin=CNF&destination=IGU&departureDate=2026-07-15&usePoints=true",
            "https://www.voeazul.com.br/br/pt/home/passagens/resultados#adults=1&journeyType=ONE_WAY&origin=CNF&destination=IGU&departureDate=2026-07-15",
        ]
        for url in test_urls:
            print(f"\nNavigating to: {url[:100]}")
            try:
                await page.goto(url, timeout=30000, wait_until="domcontentloaded")
                await asyncio.sleep(6)
                print(f"Final URL: {page.url}")
                await page.screenshot(path=f"scripts/azul_url_test_{test_urls.index(url)}.png")
            except Exception as e:
                print(f"  Error: {e}")

        # Save
        out_path = Path("C:/FlightAlert/.claude/worktrees/hopeful-johnson-30e27f/scripts/azul_responses8.json")
        out_path.write_text(json.dumps(captured, indent=2, ensure_ascii=False), encoding='utf-8')
        print(f"\n{len(captured)} responses saved to azul_responses8.json")

        # Print new endpoints found
        known = {'dpm.demdex.net', 'c.go-mpulse.net', 'fc-services-api.airtrfx.com',
                 'em-font-service-prod', 'azullinhasaereas.tt.omtrdc', 'em-prod-admin-worker',
                 'openair-california.airtrfx.com', 'vg-api.airtrfx.com', 'ct.pinterest',
                 'em-tr4ck-settings', 'mnrdszbvg02tmmt0gzqtcytdmm', 'us.creativecdn',
                 'mug.criteo', 'google-analytics', 'analytics.google', 'trc.taboola',
                 'trc-events.taboola', 'doubleclick', 'criteo', 'gum.criteo',
                 'salesforce.com', 'dpm.demdex', 'go-mpulse'}
        print("\n=== NEW unique endpoints ===")
        for r in captured:
            url = r['url']
            if not any(k in url for k in known):
                print(f"  NEW: {url[:120]}")

        await asyncio.sleep(15)
        await browser.close()

asyncio.run(discover())
