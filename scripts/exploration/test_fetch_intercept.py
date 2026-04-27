"""
Injeta um interceptor de fetch antes do MFE carregar.
Captura a resposta da API que o proprio MFE faz (que funciona com cookies validos).
"""
import asyncio
import calendar
import json
from datetime import date, datetime, timedelta
from pathlib import Path

from playwright.async_api import async_playwright
from playwright_stealth import Stealth

ORIGIN = "CNF"
DEST = "IGU"
DEPARTURE = date.today() + timedelta(days=30)

_INTERCEPT_SCRIPT = """
window.__capturedFlights = null;
window.__searchStatus = 'waiting';

const _origFetch = window.fetch.bind(window);
window.fetch = async function(input, init) {
    const url = (typeof input === 'string') ? input : (input && input.url ? input.url : String(input));

    if (url && url.includes('airlines/search')) {
        console.log('[INTERCEPTOR] Fetch para API de voos: ' + url.substring(0, 100));
        window.__searchStatus = 'fetching';
        try {
            const response = await _origFetch(input, init);
            console.log('[INTERCEPTOR] Status da resposta: ' + response.status);
            window.__searchStatus = 'status_' + response.status;

            if (response.status === 200) {
                const clone = response.clone();
                clone.json().then(data => {
                    window.__capturedFlights = data;
                    window.__searchStatus = 'done';
                    console.log('[INTERCEPTOR] Dados capturados! Keys: ' + Object.keys(data).slice(0,5).join(','));
                }).catch(e => {
                    window.__searchStatus = 'json_error';
                    console.log('[INTERCEPTOR] Erro JSON: ' + e.message);
                });
            }
            return response;
        } catch(e) {
            window.__searchStatus = 'fetch_error_' + e.message;
            console.log('[INTERCEPTOR] Erro fetch: ' + e.message);
            throw e;
        }
    }
    return _origFetch(input, init);
};

// Tambem interceptar XMLHttpRequest
const _origOpen = XMLHttpRequest.prototype.open;
const _origSend = XMLHttpRequest.prototype.send;
XMLHttpRequest.prototype.open = function(method, url, ...rest) {
    this._url = url;
    return _origOpen.apply(this, [method, url, ...rest]);
};
XMLHttpRequest.prototype.send = function(...args) {
    if (this._url && this._url.includes('airlines/search')) {
        console.log('[INTERCEPTOR] XHR para API de voos: ' + this._url.substring(0, 100));
        const xhr = this;
        const origLoad = xhr.onload;
        xhr.addEventListener('load', function() {
            try {
                const data = JSON.parse(xhr.responseText);
                window.__capturedFlights = data;
                window.__searchStatus = 'done_xhr';
                console.log('[INTERCEPTOR] XHR dados capturados!');
            } catch(e) {}
        });
    }
    return _origSend.apply(this, args);
};

console.log('[INTERCEPTOR] Fetch e XHR interceptados.');
"""


async def main():
    departure_ts = int(
        calendar.timegm(
            datetime(DEPARTURE.year, DEPARTURE.month, DEPARTURE.day).timetuple()
        )
    ) * 1000

    mfe_url = (
        f"https://www.smiles.com.br/mfe/emissao-passagem"
        f"?tripType=2&originAirport={ORIGIN}&destinationAirport={DEST}"
        f"&departureDate={departure_ts}&adults=1&children=0&infants=0"
        f"&cabinType=all&isFlexibleDateChecked=false"
    )

    async with Stealth().use_async(async_playwright()) as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()

        # Injetar o interceptor antes de qualquer script da pagina
        await context.add_init_script(_INTERCEPT_SCRIPT)

        page = await context.new_page()

        # Capturar console.log do browser para monitorar o interceptor
        page.on("console", lambda msg: print(f"  [CONSOLE] {msg.text[:120]}") if "INTERCEPTOR" in msg.text or "error" in msg.type.lower() else None)

        print(f"Carregando MFE com interceptor de fetch...")
        await page.goto(mfe_url, timeout=40000, wait_until="domcontentloaded")
        await asyncio.sleep(5)

        try:
            btn = page.locator("button:has-text('Rejeitar todos')").first
            if await btn.is_visible(timeout=3000):
                await btn.click()
                print("Cookie popup fechado")
        except Exception:
            pass

        print("\nAguardando dados serem capturados (90s)...")
        captured = None
        for i in range(90):
            status = await page.evaluate("() => window.__searchStatus")
            data = await page.evaluate("() => window.__capturedFlights")

            if data:
                captured = data
                print(f"\nDados capturados em {i+1}s! Status={status}")
                break

            if (i + 1) % 10 == 0:
                print(f"  ...{i+1}s, status={status}")

            await asyncio.sleep(1)

        await page.screenshot(path="scripts/fetch_intercept_screenshot.png", full_page=False)
        print("Screenshot: scripts/fetch_intercept_screenshot.png")

        # Tentativa final: ler o status
        final_status = await page.evaluate("() => window.__searchStatus")
        print(f"\nStatus final: {final_status}")

        await browser.close()

    if captured:
        out = Path("scripts/fetch_intercept_result.json")
        out.write_text(json.dumps(captured, indent=2, ensure_ascii=False))
        print(f"Dados salvos em: {out}")

        if "requestedFlightSegmentList" in captured:
            segs = captured["requestedFlightSegmentList"]
            total = sum(len(s.get("flightList", [])) for s in segs)
            print(f"\nVOOS: {total}")
            if segs and segs[0].get("flightList"):
                f0 = segs[0]["flightList"][0]
                avails = f0.get("availabilityList", [])
                if avails:
                    print(f"avails[0]: {json.dumps(avails[0], ensure_ascii=False)[:400]}")
        else:
            print(f"Keys: {list(captured.keys())}")
    else:
        print("Nenhum dado capturado.")


asyncio.run(main())
