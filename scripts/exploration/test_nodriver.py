"""
Usa nodriver para acessar a API do Smiles.
nodriver inicia o Chrome sem flags de automacao, evitando deteccao.
"""
import asyncio
import calendar
import json
import random
from datetime import date, datetime, timedelta
from pathlib import Path

import nodriver as uc

ORIGIN = "CNF"
DEST = "IGU"
DEPARTURE = date.today() + timedelta(days=30)

_INTERCEPT_SCRIPT = """
window.__capturedFlights = null;
window.__searchStatus = 'waiting';

const _origXHROpen = XMLHttpRequest.prototype.open;
const _origXHRSend = XMLHttpRequest.prototype.send;
XMLHttpRequest.prototype.open = function(method, url, ...rest) {
    this._url = url;
    return _origXHROpen.apply(this, [method, url, ...rest]);
};
XMLHttpRequest.prototype.send = function(...args) {
    if (this._url && this._url.includes('airlines/search')) {
        window.__searchStatus = 'fetching';
        const xhr = this;
        xhr.addEventListener('load', function() {
            if (xhr.status === 200) {
                try {
                    window.__capturedFlights = JSON.parse(xhr.responseText);
                    window.__searchStatus = 'done';
                } catch(e) { window.__searchStatus = 'json_err'; }
            } else {
                window.__searchStatus = 'error_' + xhr.status;
            }
        });
        xhr.addEventListener('error', function() {
            window.__searchStatus = 'network_error';
        });
    }
    return _origXHRSend.apply(this, args);
};

const _origFetch = window.fetch.bind(window);
window.fetch = async function(input, init) {
    const url = typeof input === 'string' ? input : (input && input.url) || '';
    if (url.includes('airlines/search')) {
        window.__searchStatus = 'fetching_fetch';
        try {
            const resp = await _origFetch(input, init);
            if (resp.status === 200) {
                const clone = resp.clone();
                clone.json().then(d => {
                    window.__capturedFlights = d;
                    window.__searchStatus = 'done_fetch';
                }).catch(() => { window.__searchStatus = 'json_err_fetch'; });
            } else {
                window.__searchStatus = 'error_fetch_' + resp.status;
            }
            return resp;
        } catch(e) {
            window.__searchStatus = 'fetch_err_' + e.message.substring(0,30);
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

    print("Iniciando nodriver (Chrome sem automacao)...")
    browser = await uc.start(headless=False, browser_args=["--window-size=1280,900"])

    try:
        # Fase 1: homepage
        print("Fase 1: Homepage Smiles...")
        page = await browser.get("https://www.smiles.com.br")
        await asyncio.sleep(4 + random.random() * 2)

        # Fechar popup cookie se aparecer
        try:
            btn = await page.find("Rejeitar todos", timeout=4)
            if btn:
                await btn.click()
                print("  Cookie popup fechado")
        except Exception:
            pass

        # Simular interacao
        await page.scroll_down(200)
        await asyncio.sleep(1)
        await page.scroll_down(200)
        await asyncio.sleep(2)

        # Injetar interceptor antes de ir para o MFE
        await page.evaluate(_INTERCEPT_SCRIPT)

        # Fase 2: MFE de busca
        print(f"\nFase 2: MFE de busca...")
        await page.get(mfe_url)
        await asyncio.sleep(5)

        # Fechar popup cookie no MFE
        try:
            btn2 = await page.find("Rejeitar todos", timeout=4)
            if btn2:
                await btn2.click()
                print("  Cookie popup fechado no MFE")
        except Exception:
            pass

        print("\nAguardando resultado da busca (90s)...")
        captured = None
        for i in range(90):
            try:
                status = await page.evaluate("() => window.__searchStatus")
                data = await page.evaluate("() => window.__capturedFlights")
            except Exception:
                status = "unknown"
                data = None

            if data:
                captured = data
                print(f"Dados capturados em {i+1}s! Status={status}")
                break

            if (i + 1) % 15 == 0:
                print(f"  ...{i+1}s, status={status}")

            await asyncio.sleep(1)

        # Status final
        try:
            final_status = await page.evaluate("() => window.__searchStatus")
            final_error_note = await page.evaluate("() => window.__searchStatus")
            print(f"\nStatus final: {final_status}")
        except Exception:
            pass

        # Screenshot
        await page.save_screenshot("scripts/nodriver_screenshot.png")
        print("Screenshot: scripts/nodriver_screenshot.png")

    finally:
        browser.stop()

    if captured:
        out = Path("scripts/nodriver_result.json")
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
