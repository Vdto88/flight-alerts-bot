"""
Coleta cookies Akamai do Smiles usando o Chrome real via CDP.

Como usar:
  1. Execute: python scripts/harvest_cookies.py
  2. No Chrome que abrir, navegue normalmente pelo Smiles
  3. Faça uma busca de voos e espere os resultados aparecerem
  4. Pressione Enter no terminal
  5. Cookies salvos — o bot usa por ~2h
"""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright

COOKIES_FILE = Path(__file__).parent / "akamai_cookies.json"
AKAMAI_NAMES = {"_abck", "ak_bmsc", "bm_sz", "bm_sv", "bm_ss"}
CDP_PORT = 9223  # porta diferente para não conflitar com Chrome já aberto

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]


def find_chrome() -> str | None:
    for path in CHROME_CANDIDATES:
        if Path(path).exists():
            return path
    return None


def _check_abck(value: str) -> str:
    parts = value.split("~")
    if len(parts) < 2:
        return "formato desconhecido"
    result = parts[1]
    if result == "0":
        return "VÁLIDO ✓"
    if result == "-1":
        return "BOT DETECTADO ✗"
    return f"código {result}"


async def main():
    chrome = find_chrome()
    if not chrome:
        print("Chrome não encontrado. Instale o Google Chrome.")
        sys.exit(1)

    print("=" * 60)
    print("  Coletor de cookies Akamai — Smiles")
    print("=" * 60)
    print()
    print("Abrindo Chrome real (perfil temporário)...")
    print()
    print("Instruções:")
    print("  1. Role a página do Smiles por alguns segundos")
    print("  2. Faça uma busca de voos normalmente")
    print("  3. Espere a lista de resultados aparecer")
    print("  4. Volte aqui e pressione Enter")
    print()

    with tempfile.TemporaryDirectory() as tmpdir:
        proc = subprocess.Popen(
            [
                chrome,
                f"--remote-debugging-port={CDP_PORT}",
                f"--user-data-dir={tmpdir}",
                "--window-size=1280,900",
                "--no-first-run",
                "--no-default-browser-check",
                "https://www.smiles.com.br",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Aguarda Chrome inicializar
        time.sleep(2)

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, input, "Pressione Enter quando terminar a busca...")

        # Conecta via CDP e extrai cookies
        cookies = []
        try:
            async with async_playwright() as p:
                browser = await p.chromium.connect_over_cdp(
                    f"http://localhost:{CDP_PORT}",
                    timeout=5000,
                )
                contexts = browser.contexts
                if contexts:
                    all_cookies = await contexts[0].cookies()
                    cookies = [
                        c for c in all_cookies
                        if c["name"] in AKAMAI_NAMES
                        and "smiles" in c.get("domain", "")
                    ]
                await browser.close()
        except Exception as e:
            print(f"\nErro ao conectar ao Chrome: {e}")
            print("Tente aumentar o tempo de espera ou verificar se o Chrome abriu corretamente.")
            proc.terminate()
            sys.exit(1)
        finally:
            proc.terminate()

    if not cookies:
        print("\nNenhum cookie Akamai encontrado.")
        print("Certifique-se de ter feito uma busca completa antes de pressionar Enter.")
        sys.exit(1)

    print(f"\nCookies coletados ({len(cookies)}):")
    abck_ok = False
    for c in cookies:
        if c["name"] == "_abck":
            status = _check_abck(c["value"])
            print(f"  _abck: {status}")
            print(f"    {c['value'][:70]}...")
            abck_ok = "VÁLIDO" in status
        else:
            print(f"  {c['name']}: {c['value'][:50]}...")

    if not abck_ok:
        print()
        print("AVISO: _abck não está validado.")
        print("Dicas para melhorar:")
        print("  - Role a página devagar antes de buscar")
        print("  - Mova o mouse pelo site")
        print("  - Espere a lista de voos aparecer completamente")
        print("  - Tente novamente")

    payload = {
        "harvested_at": datetime.now(timezone.utc).isoformat(),
        "cookies": cookies,
    }
    COOKIES_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    print()
    print(f"Cookies salvos em: {COOKIES_FILE}")
    if abck_ok:
        print("Válidos por ~2h. Pode rodar o bot agora.")


asyncio.run(main())
