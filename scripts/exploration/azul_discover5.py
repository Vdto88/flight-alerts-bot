"""
Capture booking URL from CNF->IGU Reserve agora button (no popup needed - just get href)
and also check if there's a direct booking search API.
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
        await asyncio.sleep(5)

        print("Looking for CNF->IGU buttons...")
        # Find buttons by aria-label containing CNF and IGU
        btns = await page.evaluate("""
            () => {
                const btns = document.querySelectorAll('button[aria-label*="CNF"][aria-label*="IGU"]');
                return Array.from(btns).map(b => ({
                    label: b.getAttribute('aria-label'),
                    href: b.closest('a') ? b.closest('a').href : null,
                    parentHref: b.parentElement ? (b.parentElement.tagName === 'A' ? b.parentElement.href :
                        (b.parentElement.parentElement && b.parentElement.parentElement.tagName === 'A' ?
                         b.parentElement.parentElement.href : null)) : null
                }));
            }
        """)
        print(f"Found {len(btns)} CNF->IGU buttons")
        for b in btns:
            print(f"Label: {b['label']}")
            print(f"href: {b['href']}")
            print(f"parent href: {b['parentHref']}")
            print("---")

        # Also try to find the href of anchor tags containing Reserve agora for CNF->IGU
        links = await page.evaluate("""
            () => {
                const anchors = document.querySelectorAll('a[href*="CNF"], a[href*="IGU"]');
                return Array.from(anchors).slice(0, 10).map(a => ({
                    href: a.href,
                    text: a.innerText.substring(0, 80)
                }));
            }
        """)
        print(f"\nAnchor links with CNF/IGU: {len(links)}")
        for l in links:
            print(f"  href: {l['href']}")
            print(f"  text: {l['text'][:60]}")

        # Get the data-url or similar attributes on fare cards
        fare_cards = await page.evaluate("""
            () => {
                // Look for fare card elements that might have data attributes with booking URLs
                const cards = document.querySelectorAll('[data-url], [data-booking-url], [data-href]');
                return Array.from(cards).slice(0, 10).map(c => ({
                    tag: c.tagName,
                    dataUrl: c.getAttribute('data-url') || c.getAttribute('data-booking-url') || c.getAttribute('data-href'),
                    text: c.innerText.substring(0, 60)
                }));
            }
        """)
        print(f"\nCards with data-url: {len(fare_cards)}")

        # Save responses
        scripts_dir = Path(__file__).parent
        out_path = scripts_dir / "azul_responses5.json"
        out_path.write_text(
            json.dumps(captured, indent=2, ensure_ascii=False),
            encoding='utf-8'
        )
        print(f"\n{len(captured)} responses saved to {out_path}")

        # Find graphql responses with CNF fares
        print("\n=== GraphQL CNF fares structure ===")
        for r in captured:
            if 'graphql' in r['url']:
                d = r['data']
                if isinstance(d, list):
                    for item in d:
                        if isinstance(item, dict) and 'data' in item:
                            for key, val in item['data'].items():
                                if isinstance(val, dict) and 'fares' in val:
                                    fares = val.get('fares', [])
                                    cnf_fares = [f for f in fares
                                                if 'CNF' in (str(f.get('originAirportCode','')) + str(f.get('destinationAirportCode','')))]
                                    if cnf_fares:
                                        print(f"Module '{val.get('metaData',{}).get('name','?')}':")
                                        for f in cnf_fares[:2]:
                                            print(json.dumps(f, indent=2, ensure_ascii=False))
                                        break

        await asyncio.sleep(15)
        await browser.close()

asyncio.run(discover())
