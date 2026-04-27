"""
nodriver v2 — usa CDP addScriptToEvaluateOnNewDocument para injetar
o interceptor antes do MFE carregar. Tambem verifica o _abck cookie.
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
window.__apiStatus = null;

const _origXHROpen = XMLHttpRequest.prototype.open;
const _origXHRSend = XMLHttpRequest.prototype.send;
XMLHttpRequest.prototype.open = function(method, url, ...rest) {
    this._url = url;
    return _origXHROpen.apply(this, [method, url, ...rest]);
};
XMLHttpRequest.prototype.send = function(...args) {
    if (this._url && this._url.includes('airlines/search')) {
        window.__searchStatus = 'fetching_xhr';
        window.__apiStatus = 'xhr_started';
        const xhr = this;
        xhr.addEventListener('load', function() {
            window.__apiStatus = 'xhr_status_' + xhr.status;
            if (xhr.status === 200) {
                try {
                    window.__capturedFlights = JSON.parse(xhr.responseText);
                    window.__searchStatus = 'done';
                } catch(e) { window.__searchStatus = 'json_err'; }
            } else {
                window.__searchStatus = 'error_xhr_' + xhr.status;
            }
        });
        xhr.addEventListener('error', function() {
            window.__searchStatus = 'xhr_network_error';
            window.__apiStatus = 'cors_blocked';
        });
    }
    return _origXHRSend.apply(this, args);
};

const _origFetch = window.fetch ? window.fetch.bind(window) : null;
if (_origFetch) {
    window.fetch = async function(input, init) {
        const url = typeof input === 'string' ? input : (input && input.url) || '';
        if (url.includes('airlines/search')) {
            window.__searchStatus = 'fetching_fetch';
            try {
                const resp = await _origFetch(input, init);
                window.__apiStatus = 'fetch_status_' + resp.status;
                if (resp.status === 200) {
                    const clone = resp.clone();
                    clone.json().then(d => {
                        window.__capturedFlights = d;
                        window.__searchStatus = 'done_fetch';
                    }).catch(e => { window.__searchStatus = 'json_err_fetch'; });
                } else {
                    window.__searchStatus = 'error_fetch_' + resp.status;
                }
                return resp;
            } catch(e) {
                window.__apiStatus = 'fetch_error';
                window.__searchStatus = 'fetch_err';
                throw e;
            }
        }
        return _origFetch(input, init);
    };
}
console.log('INTERCEPTOR ATIVO');
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

    print("Iniciando nodriver...")
    browser = await uc.start(headless=False, browser_args=["--window-size=1280,900"])

    try:
        # Fase 1: Homepage para aquecer Akamai
        print("Fase 1: Homepage Smiles...")
        page = await browser.get("https://www.smiles.com.br")
        await asyncio.sleep(4 + random.random() * 2)

        try:
            btn = await page.find("Rejeitar todos", timeout=4)
            if btn:
                await btn.click()
        except Exception:
            pass

        # Simular comportamento humano
        await page.scroll_down(300)
        await asyncio.sleep(1 + random.random())
        await page.scroll_down(200)
        await asyncio.sleep(2 + random.random())

        # Ler _abck na homepage via JS
        abck_hp = await page.evaluate("() => document.cookie.split('; ').find(r => r.startsWith('_abck=')) || ''")
        print(f"  _abck na homepage: {abck_hp[:60] if abck_hp else 'nao encontrado'}...")

        # Injetar script via CDP addScriptToEvaluateOnNewDocument
        print("\nInjetando interceptor via CDP...")
        try:
            await page.send(uc.cdp.page.add_script_to_evaluate_on_new_document(source=_INTERCEPT_SCRIPT))
            print("  Interceptor injetado com sucesso")
        except Exception as e:
            print(f"  Falha no CDP inject: {e}")
            # Fallback: tentar via evaluate no proximo frame
            pass

        # Fase 2: MFE
        print(f"\nFase 2: MFE...")
        await page.get(mfe_url)
        await asyncio.sleep(3)

        # Tentar injetar via evaluate tambem (redundante mas seguro)
        try:
            await page.evaluate(_INTERCEPT_SCRIPT)
        except Exception:
            pass

        try:
            btn2 = await page.find("Rejeitar todos", timeout=3)
            if btn2:
                await btn2.click()
        except Exception:
            pass

        # Ler _abck no MFE via JS
        abck_mfe = await page.evaluate("() => document.cookie.split('; ').find(r => r.startsWith('_abck=')) || ''")
        print(f"  _abck no MFE: {abck_mfe[:80] if abck_mfe else 'nao encontrado'}...")
        if abck_mfe and "=" in abck_mfe:
            val = abck_mfe.split("=", 1)[1]
            parts = val.split("~")
            print(f"  partes: {parts[:4]}")
            if len(parts) > 1:
                result = parts[1]
                print(f"  Resultado Akamai: {result} ({'BOT DETECTADO' if result == '-1' else 'VALIDO' if result == '0' else 'DESCONHECIDO'})")

        print("\nAguardando busca (90s)...")
        captured = None
        for i in range(90):
            try:
                status = await page.evaluate("() => window.__searchStatus")
                api_st = await page.evaluate("() => window.__apiStatus")
                data = await page.evaluate("() => window.__capturedFlights")
            except Exception:
                status = api_st = "eval_error"
                data = None

            if data:
                captured = data
                print(f"\nDados em {i+1}s! status={status}")
                break

            if (i + 1) % 15 == 0:
                print(f"  ...{i+1}s status={status} api={api_st}")

            await asyncio.sleep(1)

        await page.save_screenshot("scripts/nodriver2_screenshot.png")
        print("Screenshot: scripts/nodriver2_screenshot.png")

        final_s = await page.evaluate("() => window.__searchStatus")
        final_a = await page.evaluate("() => window.__apiStatus")
        print(f"\nStatus final: search={final_s} api={final_a}")

    finally:
        browser.stop()

    if captured:
        out = Path("scripts/nodriver2_result.json")
        out.write_text(json.dumps(captured, indent=2, ensure_ascii=False))
        print(f"Dados salvos: {out}")
        if "requestedFlightSegmentList" in captured:
            segs = captured["requestedFlightSegmentList"]
            total = sum(len(s.get("flightList", [])) for s in segs)
            print(f"VOOS: {total}")
    else:
        print("Nenhum dado capturado.")


asyncio.run(main())
