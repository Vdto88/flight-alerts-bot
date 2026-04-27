"""
Coleta cookies Akamai do Chrome real do usuário.

Como usar:
  1. No seu Chrome normal, acesse smiles.com.br
  2. Faça uma busca de voos e espere os resultados aparecerem
  3. COM O CHROME AINDA ABERTO, execute este script:
       python scripts/harvest_cookies.py
  4. Cookies salvos — o bot usa por ~2h

Não precisa fechar o Chrome.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import browser_cookie3
except ImportError:
    print("Instale: pip install browser-cookie3")
    sys.exit(1)

COOKIES_FILE = Path(__file__).parent / "akamai_cookies.json"
AKAMAI_NAMES = {"_abck", "ak_bmsc", "bm_sz", "bm_sv", "bm_ss"}
SMILES_DOMAIN = "smiles.com.br"


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


def main():
    print("Lendo cookies do Chrome...")

    try:
        jar = browser_cookie3.chrome(domain_name=SMILES_DOMAIN)
    except Exception as e:
        print(f"Erro ao ler cookies do Chrome: {e}")
        print()
        print("Dica: feche todas as abas do Chrome DevTools e tente novamente.")
        sys.exit(1)

    # Convert to playwright-compatible format
    cookies = []
    for c in jar:
        if c.name not in AKAMAI_NAMES:
            continue
        entry = {
            "name": c.name,
            "value": c.value,
            "domain": c.domain if c.domain else f".{SMILES_DOMAIN}",
            "path": c.path or "/",
            "secure": bool(c.secure),
            "httpOnly": False,
            "sameSite": "None",
        }
        if c.expires:
            entry["expires"] = c.expires
        cookies.append(entry)

    if not cookies:
        print()
        print("Nenhum cookie Akamai encontrado para smiles.com.br")
        print()
        print("Certifique-se de ter feito uma busca de voos no Chrome antes de rodar este script.")
        print("Depois tente novamente.")
        sys.exit(1)

    print(f"\nCookies encontrados ({len(cookies)}):")
    abck_ok = False
    for c in cookies:
        if c["name"] == "_abck":
            status = _check_abck(c["value"])
            print(f"  _abck: {status}")
            print(f"    valor: {c['value'][:70]}...")
            abck_ok = "VÁLIDO" in status
        else:
            print(f"  {c['name']}: {c['value'][:50]}...")

    if not abck_ok:
        print()
        print("AVISO: _abck não está validado (pode não funcionar).")
        print("Tente fazer a busca no Chrome de forma mais lenta:")
        print("  - Role a página antes de buscar")
        print("  - Mova o mouse pelo site")
        print("  - Espere os resultados carregarem completamente antes de rodar o script")

    payload = {
        "harvested_at": datetime.now(timezone.utc).isoformat(),
        "cookies": cookies,
    }
    COOKIES_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    print()
    print(f"Cookies salvos em: {COOKIES_FILE}")
    print("O bot usará esses cookies automaticamente. Válidos por ~2h.")


if __name__ == "__main__":
    main()
