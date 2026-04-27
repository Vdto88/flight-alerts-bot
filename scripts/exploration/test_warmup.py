"""
Estrategia: aquecer a sessao Akamai visitando a homepage do Smiles antes
de ir para o MFE. Usuarios reais nunca vao direto para o MFE.
Tambem usa o interceptor de fetch/XHR para capturar a resposta.
"""
import asyncio
import calendar
import json
import random
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
window.__searchError = null;

const _origXHROpen = XMLHttpRequest.prototype.open;
const _origXHRSend = XMLHttpRequest.prototype.send;

XMLHttpRequest.prototype.open = function(method, url, ...rest) {
    this._interceptUrl = url;
    return _origXHROpen.apply(this, [method, url, ...rest]);
};

XMLHttpRequest.prototype.send = function(...args) {
    if (this._interceptUrl && this._interceptUrl.includes('airlines/search')) {
        const xhr = this;
        window.__searchStatus = 'fetching_xhr';
        console.log('[I] XHR search: ' + this._interceptUrl.substring(0,80));
        xhr.addEventListener('load', function() {
            console.log('[I] XHR load status=' + xhr.status);
            if (xhr.status === 200) {
                try {
                    window.__capturedFlights = JSON.parse(xhr.responseText);
                    window.__searchStatus = 'done';
                } catch(e) { window.__searchError = 'json:' + e.message; }
            } else {
                window.__searchStatus = 'error_' + xhr.status;
                window.__searchError = xhr.responseText.substring(0, 200);
            }
        });
        xhr.addEventListener('error', function() {
            window.__searchStatus = 'network_error';
            console.log('[I] XHR network error');
        });
    }
    return _origXHRSend.apply(this, args);
};

const _origFetch = window.fetch.bind(window);
window.fetch = async function(input, init) {
    const url = typeof input === 'string' ? input : (input && input.url) || String(input);
    if (url && url.includes('airlines/search')) {
        window.__searchStatus = 'fetching_fetch';
        console.log('[I] fetch search: ' + url.substring(0,80));
        try {
            const resp = await _origFetch(input, init);
            console.log('[I] fetch status=' + resp.status);
            if (resp.status === 200) {
                const clone = resp.clone();
                clone.json().then(d => {
                    window.__capturedFlights = d;
                    window.__searchStatus = 'done';
                }).catch(e => { window.__searchError = 'json:' + e.message; });
            } else {
                window.__searchStatus = 'error_' + resp.status;
            }
            return resp;
        } catch(e) {
            window.__searchStatus = 'fetch_err';
            window.__searchError = e.message;
            throw e;
        }
    }
    return _origFetch(input, init);
};
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
        await context.add_init_script(_INTERCEPT_SCRIPT)

        page = await context.new_page()

        relevant_msgs = []
        page.on("console", lambda msg: relevant_msgs.append(msg.text) if "[I]" in msg.text else None)

        # FASE 1: Aquecer sessao visitando homepage
        print("Fase 1: Visitando homepage Smiles para aquecer sessao Akamai...")
        await page.goto("https://www.smiles.com.br", timeout=30000, wait_until="domcontentloaded")
        await asyncio.sleep(3 + random.random() * 2)

        # Simular movimento do mouse
        await page.mouse.move(300, 300)
        await asyncio.sleep(0.5)
        await page.mouse.move(500, 400)
        await asyncio.sleep(0.5)

        print("  Homepage carregada")

        # FASE 2: Ir para o MFE
        print("\nFase 2: Navegando para MFE de busca...")
        await page.goto(mfe_url, timeout=40000, wait_until="domcontentloaded")
        await asyncio.sleep(5)

        try:
            btn = page.locator("button:has-text('Rejeitar todos')").first
            if await btn.is_visible(timeout=3000):
                await btn.click()
                print("  Cookie popup fechado")
        except Exception:
            pass

        print("\nAguardando resultados (90s)...")
        captured = None
        for i in range(90):
            # Mostrar logs do interceptor
            while relevant_msgs:
                print(f"  [BROWSER] {relevant_msgs.pop(0)[:100]}")

            data = await page.evaluate("() => window.__capturedFlights")
            if data:
                captured = data
                print(f"\nDados capturados em {i+1}s!")
                break

            if (i + 1) % 15 == 0:
                status = await page.evaluate("() => window.__searchStatus")
                error = await page.evaluate("() => window.__searchError")
                print(f"  ...{i+1}s status={status} error={error}")

            await asyncio.sleep(1)

        # Mostrar logs restantes
        while relevant_msgs:
            print(f"  [BROWSER] {relevant_msgs.pop(0)[:100]}")

        final_status = await page.evaluate("() => window.__searchStatus")
        final_error = await page.evaluate("() => window.__searchError")
        print(f"\nStatus final: {final_status}")
        if final_error:
            print(f"Erro: {final_error}")

        await page.screenshot(path="scripts/warmup_screenshot.png", full_page=False)
        print("Screenshot: scripts/warmup_screenshot.png")
        await browser.close()

    if captured:
        out = Path("scripts/warmup_result.json")
        out.write_text(json.dumps(captured, indent=2, ensure_ascii=False))
        print(f"\nDados salvos em: {out}")

        if "requestedFlightSegmentList" in captured:
            segs = captured["requestedFlightSegmentList"]
            total = sum(len(s.get("flightList", [])) for s in segs)
            print(f"VOOS: {total}")
            if segs and segs[0].get("flightList"):
                f0 = segs[0]["flightList"][0]
                avails = f0.get("availabilityList", [])
                if avails:
                    print(f"avails[0]: {json.dumps(avails[0], ensure_ascii=False)[:400]}")
    else:
        print("Nenhum dado capturado.")


asyncio.run(main())
