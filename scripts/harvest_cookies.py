"""
Coleta cookies Akamai do Smiles via sessão real no navegador.

Como usar:
  1. Execute: python scripts/harvest_cookies.py
  2. No Chrome que abrir, faça uma busca de voos normalmente
  3. Espere a página de resultados carregar (lista de voos aparecer)
  4. Volte ao terminal e pressione Enter
  5. Cookies serão salvos e o bot poderá usá-los por ~2h
"""
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright

COOKIES_FILE = Path(__file__).parent / "akamai_cookies.json"
AKAMAI_NAMES = {"_abck", "ak_bmsc", "bm_sz", "bm_sv", "bm_ss"}


def _check_abck(value: str) -> str:
    """Interpreta o resultado do cookie _abck."""
    parts = value.split("~")
    if len(parts) < 2:
        return "formato desconhecido"
    result = parts[1]
    if result == "0":
        return "VÁLIDO ✓"
    if result == "-1":
        return "BOT DETECTADO ✗ — tente navegar mais devagar"
    return f"código {result}"


async def main():
    print("=" * 60)
    print("  Coletor de cookies Akamai — Smiles")
    print("=" * 60)
    print()
    print("Abrindo Chrome. Instruções:")
    print("  1. Navegue pelo site normalmente")
    print("  2. Faça uma busca de voos e espere os resultados")
    print("  3. Volte aqui e pressione Enter")
    print()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--window-size=1280,900", "--start-maximized"],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        page = await context.new_page()
        await page.goto("https://www.smiles.com.br")

        print("Chrome aberto em https://www.smiles.com.br")
        print()
        print("Quando terminar a busca, pressione Enter aqui...")

        # Wait for user input without blocking the event loop
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, sys.stdin.readline)

        # Collect cookies
        cookies = await context.cookies()
        akamai = [c for c in cookies if c["name"] in AKAMAI_NAMES]

        await browser.close()

    print()
    print(f"Cookies coletados ({len(akamai)}):")
    abck_ok = False
    for c in akamai:
        if c["name"] == "_abck":
            status = _check_abck(c["value"])
            print(f"  _abck: {status}")
            print(f"    valor: {c['value'][:60]}...")
            abck_ok = "VÁLIDO" in status
        else:
            print(f"  {c['name']}: {c['value'][:50]}...")

    if not akamai:
        print()
        print("ERRO: Nenhum cookie Akamai encontrado.")
        print("Certifique-se de ter feito uma busca de voos antes de pressionar Enter.")
        return

    if not abck_ok:
        print()
        print("AVISO: _abck indica bot detectado.")
        print("Tente navegar de forma mais natural: role a página, mova o mouse,")
        print("espere uns segundos antes de fazer a busca.")
        print("Salvando mesmo assim — pode funcionar parcialmente.")

    # Save with timestamp
    payload = {
        "harvested_at": datetime.now(timezone.utc).isoformat(),
        "cookies": akamai,
    }
    COOKIES_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    print()
    print(f"Cookies salvos em: {COOKIES_FILE}")
    print("O bot usará esses cookies automaticamente por ~2h.")
    print("Execute novamente quando o bot começar a retornar [] novamente.")


asyncio.run(main())
