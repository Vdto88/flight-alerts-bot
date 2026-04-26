"""
Discovers Smiles search form selectors.
Navigates to the site, dumps form elements, and attempts form interaction.
Runs headless=True (agent-safe). Saves captured API responses.

Known from prior discovery:
  - x-api-key: aJqPU7xNHl9qN3NVZnPaJ208aPo2Bh2p2ZV844tw
  - Origin input: #inputOrigin
  - Destination input: #inputDestination
  - Date input: #inputGoingOriginDate
  - Submit: #submitFlightSearch or .submitFlightSearchBtn
"""
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

ORIGIN = "CNF"
DEST = "IGU"
DATE_STR = "15/07/2026"  # DD/MM/YYYY


async def discover():
    captured_responses = []
    captured_requests = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, slow_mo=200)
        page = await browser.new_page(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ))

        async def on_request(request):
            if "flightavailability-prd.smiles.com.br" in request.url:
                headers = dict(request.headers)
                captured_requests.append({"url": request.url, "method": request.method, "headers": headers})
                print(f"[REQ] {request.method} {request.url[:120]}")

        async def on_response(response):
            if "flightavailability-prd.smiles.com.br" in response.url:
                print(f"[RESP {response.status}] {response.url[:120]}")
                try:
                    ct = response.headers.get("content-type", "")
                    if "json" in ct:
                        data = await response.json()
                        captured_responses.append({"url": response.url, "status": response.status, "data": data})
                        if response.status == 200 and "searchflights" in response.url:
                            Path("scripts").mkdir(exist_ok=True)
                            Path("scripts/smiles_real_response.json").write_text(
                                json.dumps(data, indent=2, ensure_ascii=False)
                            )
                            print("[API] Flight search response saved to scripts/smiles_real_response.json")
                    else:
                        body = await response.text()
                        captured_responses.append({"url": response.url, "status": response.status, "body": body[:500]})
                except Exception as e:
                    print(f"[RESP] Error reading response: {e}")

        page.on("request", on_request)
        page.on("response", on_response)

        print("Navigating to Smiles search page...")
        await page.goto("https://www.smiles.com.br/passagens-aereas", timeout=30000)
        await page.wait_for_load_state("domcontentloaded")
        await asyncio.sleep(3)

        # Dump form elements
        elements = await page.evaluate("""
            () => {
                const inputs = document.querySelectorAll('input, [data-testid], [aria-label], button[type="submit"], #submitFlightSearch, .submitFlightSearchBtn');
                return Array.from(inputs).slice(0, 60).map(el => ({
                    tag: el.tagName,
                    type: el.type || '',
                    id: el.id || '',
                    name: el.name || '',
                    placeholder: el.placeholder || '',
                    ariaLabel: el.getAttribute('aria-label') || '',
                    dataTestId: el.getAttribute('data-testid') || '',
                    className: el.className ? el.className.substring(0, 80) : '',
                    value: el.value ? el.value.substring(0, 50) : ''
                }));
            }
        """)
        print("\n=== FORM ELEMENTS ===")
        for el in elements:
            if el.get('id') or el.get('placeholder') or el.get('ariaLabel') or el.get('type') == 'submit':
                print(json.dumps(el))

        # Check if known selectors exist
        for selector in ['#inputOrigin', '#inputDestination', '#inputGoingOriginDate', '#submitFlightSearch', '.submitFlightSearchBtn']:
            count = await page.locator(selector).count()
            print(f"  Selector '{selector}': {count} element(s)")

        # Try form interaction
        print("\n=== ATTEMPTING FORM INTERACTION ===")
        try:
            # Fill origin
            origin_count = await page.locator('#inputOrigin').count()
            if origin_count > 0:
                await page.fill('#inputOrigin', ORIGIN)
                await asyncio.sleep(1)
                # Click first suggestion
                suggestion = page.locator('ul#ulOriginAirport li, .airport-suggestion, [class*="suggestion"]').first
                sug_count = await page.locator('ul#ulOriginAirport li, .airport-suggestion').count()
                print(f"  Origin suggestions: {sug_count}")
                if sug_count > 0:
                    await suggestion.click()
                    await asyncio.sleep(0.5)
                print("  Origin filled")
            else:
                print("  #inputOrigin NOT FOUND")

            # Fill destination
            dest_count = await page.locator('#inputDestination').count()
            if dest_count > 0:
                await page.fill('#inputDestination', DEST)
                await asyncio.sleep(1)
                sug_count = await page.locator('ul#ulDestinationAirport li, .airport-suggestion').count()
                print(f"  Destination suggestions: {sug_count}")
                if sug_count > 0:
                    await page.locator('ul#ulDestinationAirport li, .airport-suggestion').first.click()
                    await asyncio.sleep(0.5)
                print("  Destination filled")
            else:
                print("  #inputDestination NOT FOUND")

            # Fill date
            date_count = await page.locator('#inputGoingOriginDate').count()
            if date_count > 0:
                await page.fill('#inputGoingOriginDate', DATE_STR)
                await asyncio.sleep(0.5)
                print(f"  Date filled: {DATE_STR}")
            else:
                print("  #inputGoingOriginDate NOT FOUND")

            # Click submit
            submit_count = await page.locator('#submitFlightSearch').count()
            submit_btn_count = await page.locator('.submitFlightSearchBtn').count()
            print(f"  #submitFlightSearch: {submit_count}, .submitFlightSearchBtn: {submit_btn_count}")
            if submit_count > 0:
                await page.click('#submitFlightSearch')
                print("  Clicked #submitFlightSearch")
            elif submit_btn_count > 0:
                await page.locator('.submitFlightSearchBtn').first.click()
                print("  Clicked .submitFlightSearchBtn")
            else:
                print("  No submit button found!")

            # Wait for API response
            print("  Waiting for API response (15s)...")
            await asyncio.sleep(15)

        except Exception as e:
            print(f"  Form interaction error: {e}")

        print(f"\n=== RESULTS ===")
        print(f"Flight API requests captured: {len(captured_requests)}")
        print(f"Flight API responses captured: {len(captured_responses)}")
        for r in captured_responses:
            keys = list(r.get('data', {}).keys()) if isinstance(r.get('data'), dict) else 'N/A'
            print(f"  {r['status']} {r['url'][:80]} keys={keys}")

        Path("scripts").mkdir(exist_ok=True)
        Path("scripts/smiles_form_discover.json").write_text(
            json.dumps({"requests": captured_requests, "responses": captured_responses}, indent=2, ensure_ascii=False)
        )
        print("Saved to scripts/smiles_form_discover.json")

        await browser.close()


asyncio.run(discover())
