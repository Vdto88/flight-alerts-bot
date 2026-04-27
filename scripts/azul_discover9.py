"""
Use www.voeazul.com.br to find the real award flight search API.
This is Azul's actual booking platform (not the airtrfx deals widget).
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
        context = await browser.new_context(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ))
        page = await context.new_page()

        async def capture(response):
            url = response.url
            if response.status == 200:
                ct = response.headers.get("content-type", "")
                if "json" in ct:
                    try:
                        data = await response.json()
                        captured.append({"url": url, "data": data})
                        # Print interesting URLs
                        if any(x in url for x in ['voeazul', 'b2c-api', 'azul']) and 'analytics' not in url:
                            print(f"[JSON 200] {url[:120]}")
                    except Exception:
                        pass
            if response.status not in (200, 204, 301, 302, 202, 201):
                u = response.url
                if any(x in u for x in ['voeazul', 'b2c-api', 'azul']) and 'analytics' not in u:
                    print(f"  [{response.status}] {u[:120]}")

        page.on("response", capture)

        # Navigate to the main Azul booking page
        print("Loading www.voeazul.com.br...")
        await page.goto("https://www.voeazul.com.br/br/pt/home",
                        timeout=60000, wait_until="domcontentloaded")
        await asyncio.sleep(6)

        try:
            await page.click('text=Aceitar', timeout=3000)
            await asyncio.sleep(1)
        except Exception:
            pass

        # Print form elements
        elements = await page.evaluate("""
            () => {
                const els = document.querySelectorAll('input[placeholder], button[aria-label], [data-testid], select');
                return Array.from(els).slice(0, 50).map(el => ({
                    tag: el.tagName,
                    id: el.id || '',
                    placeholder: el.placeholder || '',
                    ariaLabel: el.getAttribute('aria-label') || '',
                    dataTestId: el.getAttribute('data-testid') || '',
                    text: el.innerText ? el.innerText.substring(0, 40) : ''
                }));
            }
        """)
        print("\n=== FORM ELEMENTS on www.voeazul.com.br ===")
        for el in elements:
            if any([el['placeholder'], el['ariaLabel'], el['dataTestId'], el['id']]):
                print(json.dumps(el, ensure_ascii=False))

        # Take screenshot
        await page.screenshot(path="scripts/azul_main_site.png")
        print("\nScreenshot: azul_main_site.png")

        # Look for a way to switch to pontos/miles search
        print("\nLooking for points/miles mode toggle...")
        mode_info = await page.evaluate("""
            () => {
                // Find buttons/links related to points/miles
                const allBtns = document.querySelectorAll('button, a, label, input[type="radio"]');
                const relevant = Array.from(allBtns).filter(el => {
                    const txt = (el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('for') || '').toLowerCase();
                    return txt.includes('pont') || txt.includes('mile') || txt.includes('resgate') || txt.includes('fidelidade');
                });
                return relevant.slice(0, 10).map(el => ({
                    tag: el.tagName,
                    text: (el.innerText || el.value || '').substring(0, 60),
                    ariaLabel: el.getAttribute('aria-label') || '',
                    id: el.id,
                    name: el.name || '',
                    type: el.type || '',
                    href: el.href || ''
                }));
            }
        """)
        print("Points-related elements:")
        for el in mode_info:
            print(f"  {el}")

        print("\nWaiting 90s for manual interaction...")
        print("Please: switch to Pontos mode, fill CNF -> IGU, pick a date, and click search.")
        await asyncio.sleep(90)

        # Save
        out_path = Path("C:/FlightAlert/.claude/worktrees/hopeful-johnson-30e27f/scripts/azul_responses9.json")
        out_path.write_text(json.dumps(captured, indent=2, ensure_ascii=False), encoding='utf-8')
        print(f"\n{len(captured)} responses saved")

        # Print new endpoints
        known = {'c.go-mpulse.net', 'fc-services-api.airtrfx', 'em-font-service',
                 'azullinhasaereas.tt.omtrdc', 'em-prod-admin-worker', 'openair-california',
                 'vg-api.airtrfx', 'ct.pinterest', 'em-tr4ck-settings', 'creativecdn',
                 'mug.criteo', 'google-analytics', 'analytics.google', 'trc.taboola',
                 'trc-events.taboola', 'doubleclick', 'criteo', 'gum.criteo', 'salesforce',
                 'dpm.demdex', 'firebase', 'googleapis', 'publish-p135570'}
        print("\n=== All non-tracker URLs ===")
        seen = set()
        for r in captured:
            url = r['url']
            base = url.split('?')[0]
            if base not in seen and not any(k in url for k in known):
                seen.add(base)
                d = r['data']
                if isinstance(d, dict):
                    print(f"  {url[:120]} -> keys={list(d.keys())[:6]}")
                else:
                    print(f"  {url[:120]} -> list")

        await browser.close()

asyncio.run(discover())
