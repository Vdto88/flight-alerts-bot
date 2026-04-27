"""
Click CNF->IGU Reserve agora button via JavaScript click to bypass visibility issues.
Also try main booking form with pontos mode.
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
                        # Only print interesting ones
                        if any(x in url for x in ['airtrfx', 'voeazul', 'azul']):
                            if 'analytics' not in url:
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

        # Get the href/link from fare cards
        href_info = await page.evaluate("""
            () => {
                // Find all CNF->IGU fare card elements - look for enclosing <a> tags
                const allAnchors = document.querySelectorAll('a');
                const cnfLinks = Array.from(allAnchors).filter(a =>
                    a.getAttribute('aria-label') && a.getAttribute('aria-label').includes('CNF')
                    || a.href && (a.href.includes('CNF') || a.href.includes('IGU'))
                );

                // Also get button.onclick content
                const cnfBtns = document.querySelectorAll('button[aria-label*="CNF"][aria-label*="IGU"]');
                const btnInfo = Array.from(cnfBtns).slice(0, 2).map(b => {
                    // Get the closest anchor parent
                    let el = b;
                    while (el && el.tagName !== 'A' && el.tagName !== 'BODY') {
                        el = el.parentElement;
                    }
                    return {
                        label: b.getAttribute('aria-label'),
                        closestAnchor: el && el.tagName === 'A' ? el.href : null,
                        // Get onclick
                        onClick: b.onclick ? b.onclick.toString().substring(0, 200) : null
                    };
                });

                return {
                    cnfLinks: cnfLinks.slice(0, 5).map(a => ({href: a.href, label: a.getAttribute('aria-label')})),
                    btnInfo: btnInfo
                };
            }
        """)
        print("CNF links:", json.dumps(href_info['cnfLinks'], indent=2, ensure_ascii=False))
        print("Button info:", json.dumps(href_info['btnInfo'], indent=2, ensure_ascii=False))

        # Try JavaScript direct click on first CNF->IGU button
        print("\nUsing JS to get button and extract click URL...")
        click_result = await page.evaluate("""
            () => {
                const btn = document.querySelector('button[aria-label*="CNF"][aria-label*="IGU"]');
                if (!btn) return {error: 'no button found'};

                // Look for any data attributes
                const attrs = {};
                for (const attr of btn.attributes) {
                    attrs[attr.name] = attr.value;
                }

                // Check parent elements for links
                let el = btn;
                const ancestry = [];
                for (let i = 0; i < 8; i++) {
                    if (!el) break;
                    ancestry.push({
                        tag: el.tagName,
                        id: el.id || null,
                        href: el.href || null,
                        classes: el.className ? el.className.substring(0, 60) : null
                    });
                    el = el.parentElement;
                }

                return {attrs, ancestry};
            }
        """)
        print("Click result:", json.dumps(click_result, indent=2, ensure_ascii=False))

        # Try JS click to fire the button and see URL navigation
        print("\nJS click on CNF->IGU button...")
        await page.evaluate("""
            () => {
                const btn = document.querySelector('button[aria-label*="CNF"][aria-label*="IGU"]');
                if (btn) btn.click();
            }
        """)
        await asyncio.sleep(5)
        print(f"URL after JS click: {page.url}")
        await page.screenshot(path="scripts/azul_js_click.png")

        # ===== PHASE 2: Top booking form with Reserve com Pontos =====
        print("\n=== PHASE 2: Top booking form - switching to Pontos mode ===")
        # Go back if navigated away
        if 'home' not in page.url:
            await page.goto("https://passagens.voeazul.com.br/br/pt/home",
                            timeout=60000, wait_until="domcontentloaded")
            await asyncio.sleep(5)
            try:
                await page.click('text=Aceitar', timeout=2000)
            except Exception:
                pass
            await asyncio.sleep(2)

        # Click the "Reserve com Reais" dropdown to switch to points mode
        try:
            # Look for any listbox button with "Reais" or "Pontos"
            mode_btn = page.locator('#headlessui-listbox-button-6')
            mode_text = await mode_btn.text_content()
            print(f"Mode button: {mode_text}")
            await mode_btn.click()
            await asyncio.sleep(2)

            # Look for options
            all_options = await page.evaluate("""
                () => {
                    const opts = document.querySelectorAll('[role="option"]');
                    return Array.from(opts).map(o => o.innerText.trim().substring(0, 60));
                }
            """)
            print(f"Options: {all_options}")

            # Click Reserve com Pontos
            for opt_text in ['Reserve com Pontos', 'Pontos', 'pontos']:
                try:
                    opt = page.get_by_role('option', name=opt_text, exact=False)
                    if await opt.count() > 0:
                        await opt.click()
                        print(f"Clicked option: {opt_text}")
                        break
                except Exception:
                    pass
            await asyncio.sleep(2)
        except Exception as e:
            print(f"Mode switch error: {e}")

        # Fill top form
        print("Filling top form: CNF -> IGU...")
        try:
            origin_top = '#cross-sell-search-panel-id-1-input'
            await page.click(origin_top)
            await asyncio.sleep(0.5)
            await page.fill(origin_top, 'CNF')
            await asyncio.sleep(2)
            options = page.locator('[role="option"]')
            if await options.count() > 0:
                await options.first.click()
            await asyncio.sleep(1)

            dest_top = '#cross-sell-search-panel-id-2-input'
            await page.click(dest_top)
            await asyncio.sleep(0.5)
            await page.fill(dest_top, 'IGU')
            await asyncio.sleep(2)
            options = page.locator('[role="option"]')
            if await options.count() > 0:
                await options.first.click()
            await asyncio.sleep(1)
        except Exception as e:
            print(f"Top form fill error: {e}")

        # Try pressing Enter or clicking search button
        try:
            # The form might use a search icon button or pressing Enter
            await page.keyboard.press('Enter')
            await asyncio.sleep(8)
            print(f"URL after Enter: {page.url}")
            await page.screenshot(path="scripts/azul_top_form.png")
        except Exception as e:
            print(f"Error: {e}")

        # Save all responses
        out_path = Path("C:/FlightAlert/.claude/worktrees/hopeful-johnson-30e27f/scripts/azul_responses7.json")
        out_path.write_text(
            json.dumps(captured, indent=2, ensure_ascii=False),
            encoding='utf-8'
        )
        print(f"\n{len(captured)} responses saved")

        await asyncio.sleep(15)
        await browser.close()

asyncio.run(discover())
