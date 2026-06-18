# Painel web filtrável de passagens — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publicar um painel web estático (GitHub Pages) que mostra a tarifa mais barata por rota+data do último run do bot, filtrável/ordenável e protegido por senha (JSON cifrado).

**Architecture:** O cron que já existe gera, sem queries extras, um `deals.json` (a partir dos voos já buscados). O workflow cifra esse JSON com a senha (secret) e publica `web/` + `deals.enc.json` via GitHub Actions Pages artifact — nada é commitado no repo. A página decifra no navegador (WebCrypto) e renderiza a tabela. O Telegram não muda.

**Tech Stack:** Python 3.11, `cryptography` (PBKDF2 + AES-GCM), HTML/CSS/JS vanilla + WebCrypto, GitHub Actions Pages (`actions/upload-pages-artifact`, `actions/deploy-pages`).

## Global Constraints

- Python 3.11. Rodar testes sempre com `python -m pytest` (nunca `pytest` puro) a partir de `C:\FlightAlert`.
- Trabalhar em `C:\FlightAlert` (ignorar o worktree vazio).
- `git add` sempre com caminhos explícitos — nunca `git add .`.
- Todo commit termina com o trailer `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- Cripto: PBKDF2-HMAC-SHA256, 200000 iterações, chave AES-256; AES-GCM com salt de 16 bytes e IV de 12 bytes, ambos aleatórios por arquivo. Formato do `deals.enc.json`: `{"v":1,"kdf":"PBKDF2-SHA256","iterations":200000,"salt":b64,"iv":b64,"ciphertext":b64}` (ciphertext = corpo + tag GCM, como o WebCrypto espera).
- Deploy via artifact: o `master` NÃO recebe commits de dados. `deals.json` e `deals.enc.json` são artefatos (gitignored).
- Telegram inalterado; price-watches são any-airline (já decidido).
- Snapshot sobrescreve a cada run (sem histórico).

## File Structure

- `panel.py` (novo) — `build_deals` (puro) + `write_deals` (IO). Responsável por transformar voos em registros de deal e serializar.
- `scripts/encrypt_deals.py` (novo) — cifra `deals.json` → `deals.enc.json`; também expõe `decrypt` para testes/paridade.
- `cycle.py` (modificar) — acumula deals por rota e grava `deals.json` ao final.
- `web/index.html`, `web/app.js`, `web/style.css` (novos) — front estático: gate de senha, decifra, tabela filtrável.
- `requirements.txt` (modificar) — adicionar `cryptography`.
- `.gitignore` (modificar) — ignorar `deals.json` e `deals.enc.json`.
- `.github/workflows/azul-alert.yml` (modificar) — steps de cifrar + deploy Pages + permissões.
- `tests/test_panel.py`, `tests/test_encrypt_deals.py` (novos); `tests/test_cycle.py` (modificar).

---

### Task 1: `panel.build_deals` (função pura)

**Files:**
- Create: `panel.py`
- Test: `tests/test_panel.py`

**Interfaces:**
- Consumes: `airlines.base.Flight`; `config.PriceWatch`; `alerts.evaluate`, `alerts.evaluate_threshold`.
- Produces: `panel.build_deals(flights: list[Flight], region: str, watches: list[PriceWatch]) -> list[dict]`. Cada dict tem as chaves: `origem, destino, regiao, cia, data` (ISO `YYYY-MM-DD`), `hora, preco` (float), `paradas` (int), `direto` (bool), `url_compra, azul_cheapest` (bool), `price_watch` (float|None). Uma entrada por data com a tarifa mais barata (qualquer cia, `price > 0`).

- [ ] **Step 1: Write the failing test**

```python
from datetime import date

import panel
from airlines.base import Flight
from config import PriceWatch, month


def _f(airline, price, d=date(2026, 9, 10), dest="SJK", stops=0):
    return Flight("CNF", dest, airline, d, "08h00", "09h00", price, stops == 0, stops, "http://buy")


def test_build_deals_cheapest_per_date():
    deals = panel.build_deals([_f("GOL", 420.0), _f("Azul", 380.0), _f("LATAM", 500.0)], "São Paulo", [])
    assert len(deals) == 1
    d = deals[0]
    assert d["cia"] == "Azul" and d["preco"] == 380.0
    assert d["regiao"] == "São Paulo"
    assert d["origem"] == "CNF" and d["destino"] == "SJK"
    assert d["data"] == "2026-09-10" and d["hora"] == "08h00"
    assert d["direto"] is True and d["paradas"] == 0
    assert d["url_compra"] == "http://buy"


def test_build_deals_ignores_nonpositive_price():
    deals = panel.build_deals([_f("Azul", 0.0), _f("GOL", 420.0)], "SP", [])
    assert len(deals) == 1
    assert deals[0]["cia"] == "GOL" and deals[0]["preco"] == 420.0


def test_build_deals_azul_cheapest_flag_true():
    deals = panel.build_deals([_f("Azul", 300.0), _f("LATAM", 450.0)], "SP", [])
    assert deals[0]["azul_cheapest"] is True


def test_build_deals_azul_cheapest_flag_false_when_not_cheapest():
    deals = panel.build_deals([_f("Azul", 500.0), _f("GOL", 300.0)], "SP", [])
    assert deals[0]["azul_cheapest"] is False
    assert deals[0]["cia"] == "GOL"


def test_build_deals_price_watch_flag():
    watches = [PriceWatch("SJK", month(2026, 9), 400.0)]
    deals = panel.build_deals([_f("GOL", 380.0)], "SP", watches)
    assert deals[0]["price_watch"] == 400.0
    assert panel.build_deals([_f("GOL", 380.0)], "SP", [])[0]["price_watch"] is None


def test_build_deals_empty():
    assert panel.build_deals([], "SP", []) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_panel.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'panel'`.

- [ ] **Step 3: Write minimal implementation**

Create `panel.py`:

```python
import alerts
from airlines.base import Flight
from config import PriceWatch


def build_deals(flights: list[Flight], region: str, watches: list[PriceWatch]) -> list[dict]:
    """For one route's flights, one record per date = the cheapest fare (any airline,
    price > 0). Signal flags reuse alerts.evaluate / evaluate_threshold as the single
    source of truth."""
    valid = [f for f in flights if f.price is not None and f.price > 0]
    by_date: dict = {}
    for f in valid:
        by_date.setdefault(f.departure_date, []).append(f)

    azul_dates = {a.flight.departure_date for a in alerts.evaluate(flights)}
    watch_by_date = {
        t.flight.departure_date: t.max_price
        for t in alerts.evaluate_threshold(flights, watches)
    }

    deals: list[dict] = []
    for d, day_flights in by_date.items():
        cheapest = min(day_flights, key=lambda f: f.price)
        deals.append({
            "origem": cheapest.origin,
            "destino": cheapest.destination,
            "regiao": region,
            "cia": cheapest.airline,
            "data": d.isoformat(),
            "hora": cheapest.departure_time,
            "preco": cheapest.price,
            "paradas": cheapest.stops,
            "direto": cheapest.is_direct,
            "url_compra": cheapest.booking_url,
            "azul_cheapest": d in azul_dates,
            "price_watch": watch_by_date.get(d),
        })
    return deals
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_panel.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add panel.py tests/test_panel.py
git commit -m "feat(panel): build_deals — cheapest fare per route+date with signal flags

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: `panel.write_deals` (serializer)

**Files:**
- Modify: `panel.py`
- Test: `tests/test_panel.py`

**Interfaces:**
- Produces: `panel.write_deals(deals: list[dict], path: str, generated_at: datetime | None = None) -> str`. Escreve `{"gerado_em": <ISO8601 UTC, sufixo "Z">, "deals": [...]}` em UTF-8 (`ensure_ascii=False`); retorna `path`.

- [ ] **Step 1: Write the failing test**

Adicione a `tests/test_panel.py`:

```python
import json
from datetime import datetime, timezone


def test_write_deals_roundtrip(tmp_path):
    out = tmp_path / "deals.json"
    deals = [{"origem": "CNF", "destino": "GIG", "regiao": "Rio de Janeiro", "preco": 289.0}]
    ts = datetime(2026, 6, 18, 11, 3, 0, tzinfo=timezone.utc)
    ret = panel.write_deals(deals, str(out), generated_at=ts)
    assert ret == str(out)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["gerado_em"] == "2026-06-18T11:03:00Z"
    assert data["deals"] == deals


def test_write_deals_defaults_timestamp(tmp_path):
    out = tmp_path / "deals.json"
    panel.write_deals([], str(out))
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["gerado_em"].endswith("Z") and data["deals"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_panel.py -k write_deals -v`
Expected: FAIL — `AttributeError: module 'panel' has no attribute 'write_deals'`.

- [ ] **Step 3: Write minimal implementation**

Adicione ao topo de `panel.py` (imports) e ao corpo:

```python
import json
from datetime import datetime, timezone
```

```python
def write_deals(deals: list[dict], path: str, generated_at: datetime | None = None) -> str:
    ts = generated_at or datetime.now(timezone.utc)
    payload = {"gerado_em": ts.strftime("%Y-%m-%dT%H:%M:%SZ"), "deals": deals}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    return path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_panel.py -v`
Expected: PASS (8 passed).

- [ ] **Step 5: Commit**

```bash
git add panel.py tests/test_panel.py
git commit -m "feat(panel): write_deals — serialize snapshot with UTC timestamp

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Gravar `deals.json` no ciclo

**Files:**
- Modify: `cycle.py`
- Modify: `.gitignore`
- Test: `tests/test_cycle.py`

**Interfaces:**
- Consumes: `panel.build_deals`, `panel.write_deals` (Tasks 1–2); `routing.group_of`.
- Produces: módulo `cycle` ganha a constante `DEALS_PATH = "deals.json"`; `run_azul_cycle()` grava o snapshot ao final usando os voos já buscados (zero query extra).

- [ ] **Step 1: Write the failing test**

Adicione a `tests/test_cycle.py` (o topo do arquivo já importa `config, cache, routing, telegram_bot, cycle`, `Flight` e `GoogleFlightsSearcher`; adicione `import json`):

```python
async def test_run_cycle_writes_deals_json(monkeypatch, tmp_path):
    await cache.init_db()
    d = date(2026, 7, 15)
    canned = [
        Flight("CNF", "GIG", "Azul", d, "12h00", "13h15", 300.0, True, 0, "http://buy"),
        Flight("CNF", "GIG", "LATAM", d, "07h00", "08h15", 396.0, True, 0, "http://buy"),
    ]

    async def fake_search_dates(self, origin, destination, dates, batch_size=7):
        return canned if (origin, destination) == ("CNF", "GIG") else []

    monkeypatch.setattr(GoogleFlightsSearcher, "search_dates", fake_search_dates)
    monkeypatch.setattr(cycle, "GROUPS", [config.Group("Rio de Janeiro", ("GIG",), topic_id=4)])
    monkeypatch.setattr(cycle, "PRICE_WATCHES", [])

    async def ok_azul(flight, comparison, topic_id=None):
        return True

    async def ok_price(flight, max_price, topic_id=None):
        return True

    monkeypatch.setattr(telegram_bot, "send_azul_alert", ok_azul)
    monkeypatch.setattr(telegram_bot, "send_price_alert", ok_price)

    out = tmp_path / "deals.json"
    monkeypatch.setattr(cycle, "DEALS_PATH", str(out))

    await cycle.run_azul_cycle()

    data = json.loads(out.read_text(encoding="utf-8"))
    assert "gerado_em" in data
    gig = [x for x in data["deals"] if x["destino"] == "GIG"]
    assert len(gig) == 1
    assert gig[0]["cia"] == "Azul" and gig[0]["preco"] == 300.0
    assert gig[0]["regiao"] == "Rio de Janeiro"
    assert gig[0]["azul_cheapest"] is True
    assert gig[0]["price_watch"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cycle.py::test_run_cycle_writes_deals_json -v`
Expected: FAIL — `AttributeError: module 'cycle' has no attribute 'DEALS_PATH'`.

- [ ] **Step 3: Write minimal implementation**

Em `cycle.py`:

(a) Adicione `import panel` junto aos outros imports (após `import routing`).

(b) Após a linha `_searcher = GoogleFlightsSearcher()`, adicione:

```python
DEALS_PATH = "deals.json"
```

(c) Dentro de `run_azul_cycle`, logo após `total_errors = 0`, adicione:

```python
    all_deals: list[dict] = []
```

(d) Dentro do `for route in ...`, logo após o bloco do "Signal 2" (o `for pa in evaluate_threshold(...)`) e antes do `logger.info(...)` da rota, adicione:

```python
        group = routing.group_of(route.non_hub, GROUPS)
        region = group.name if group else route.non_hub
        all_deals.extend(panel.build_deals(flights, region, watches))
```

(e) Após o `for route` (antes do `logger.info("CICLO AZUL CONCLUÍDO ...")` final), adicione:

```python
    panel.write_deals(all_deals, DEALS_PATH)
    logger.info(f"deals snapshot: {len(all_deals)} registros → {DEALS_PATH}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cycle.py -v`
Expected: PASS (todos, incluindo o novo). Depois rode a suíte inteira:
Run: `python -m pytest -q`
Expected: PASS, sem falhas (deve ser 145 = 136 atuais + 8 de `test_panel.py` + 1 novo em `test_cycle.py`; confirme pelo número que o pytest reportar).

- [ ] **Step 5: Update `.gitignore`**

Adicione ao final de `.gitignore`:

```
deals.json
deals.enc.json
```

- [ ] **Step 6: Commit**

```bash
git add cycle.py tests/test_cycle.py .gitignore
git commit -m "feat(cycle): write deals.json snapshot from already-fetched flights

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: `scripts/encrypt_deals.py` + dependência

**Files:**
- Create: `scripts/encrypt_deals.py`
- Modify: `requirements.txt`
- Test: `tests/test_encrypt_deals.py`

**Interfaces:**
- Produces: `scripts.encrypt_deals.encrypt_file(in_path: str, out_path: str, password: str) -> str` e `scripts.encrypt_deals.decrypt(payload: dict, password: str) -> bytes`. CLI `__main__` lê `PANEL_PASSWORD` do ambiente e cifra `deals.json` → `deals.enc.json`. `scripts` é importável como namespace package (repo root está no `sys.path` dos testes).

- [ ] **Step 1: Add the dependency**

Adicione `cryptography` em `requirements.txt` (uma linha nova). Depois instale:
Run: `pip install cryptography`
Expected: instala sem erro.

- [ ] **Step 2: Write the failing test**

Create `tests/test_encrypt_deals.py`:

```python
import json
import pytest

from scripts.encrypt_deals import encrypt_file, decrypt


def test_encrypt_then_decrypt_roundtrip(tmp_path):
    src = tmp_path / "deals.json"
    src.write_text('{"gerado_em":"2026-06-18T11:03:00Z","deals":[{"preco":289.0}]}', encoding="utf-8")
    out = tmp_path / "deals.enc.json"

    encrypt_file(str(src), str(out), "segredo")

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["v"] == 1 and payload["kdf"] == "PBKDF2-SHA256"
    assert payload["iterations"] == 200000
    assert payload["salt"] and payload["iv"] and payload["ciphertext"]

    clear = decrypt(payload, "segredo")
    assert json.loads(clear)["deals"][0]["preco"] == 289.0


def test_decrypt_wrong_password_raises(tmp_path):
    src = tmp_path / "deals.json"
    src.write_text('{"deals":[]}', encoding="utf-8")
    out = tmp_path / "deals.enc.json"
    encrypt_file(str(src), str(out), "certa")
    payload = json.loads(out.read_text(encoding="utf-8"))
    with pytest.raises(Exception):
        decrypt(payload, "errada")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_encrypt_deals.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.encrypt_deals'`.

- [ ] **Step 4: Write minimal implementation**

Create `scripts/encrypt_deals.py`:

```python
import base64
import json
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ITERATIONS = 200000


def _derive_key(password: str, salt: bytes, iterations: int) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations)
    return kdf.derive(password.encode("utf-8"))


def encrypt_file(in_path: str, out_path: str, password: str) -> str:
    with open(in_path, "rb") as fh:
        plaintext = fh.read()
    salt = os.urandom(16)
    iv = os.urandom(12)
    key = _derive_key(password, salt, ITERATIONS)
    ciphertext = AESGCM(key).encrypt(iv, plaintext, None)
    payload = {
        "v": 1,
        "kdf": "PBKDF2-SHA256",
        "iterations": ITERATIONS,
        "salt": base64.b64encode(salt).decode("ascii"),
        "iv": base64.b64encode(iv).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
    }
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    return out_path


def decrypt(payload: dict, password: str) -> bytes:
    salt = base64.b64decode(payload["salt"])
    iv = base64.b64decode(payload["iv"])
    ciphertext = base64.b64decode(payload["ciphertext"])
    key = _derive_key(password, salt, payload["iterations"])
    return AESGCM(key).decrypt(iv, ciphertext, None)


if __name__ == "__main__":
    encrypt_file("deals.json", "deals.enc.json", os.environ["PANEL_PASSWORD"])
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_encrypt_deals.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add scripts/encrypt_deals.py tests/test_encrypt_deals.py requirements.txt
git commit -m "feat(panel): encrypt_deals — AES-GCM + PBKDF2 for the published JSON

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Front estático `web/` (gate de senha + tabela filtrável)

**Files:**
- Create: `web/index.html`, `web/style.css`, `web/app.js`

**Interfaces:**
- Consumes: `deals.enc.json` no formato da Task 4 (servido ao lado do `index.html`); o JSON decifrado tem `{gerado_em, deals: [...]}` com as chaves da Task 1.
- Produces: site estático. Verificação é manual (browser) — não há teste automatizado de front.

- [ ] **Step 1: Create `web/index.html`**

```html
<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Passagens — saindo de CNF</title>
  <link rel="stylesheet" href="style.css" />
</head>
<body>
  <main>
    <section id="gate">
      <h1>Passagens</h1>
      <p>Digite a senha para ver os deals.</p>
      <input id="password" type="password" autocomplete="current-password" placeholder="senha" />
      <button id="unlock">Entrar</button>
      <p id="error" class="error" hidden>Senha incorreta.</p>
    </section>

    <section id="app" hidden>
      <header>
        <h1>Passagens — saindo de CNF</h1>
        <span id="updated" class="muted"></span>
      </header>

      <div id="summary" class="cards"></div>

      <div id="filters">
        <select id="f-regiao"></select>
        <select id="f-aeroporto"></select>
        <select id="f-cia"></select>
        <select id="f-tipo">
          <option value="">Tipo: todos</option>
          <option value="azul">Azul mais barata</option>
          <option value="watch">Price-watch</option>
        </select>
        <select id="f-mes"></select>
        <label class="check"><input id="f-direto" type="checkbox" /> só diretos</label>
        <label class="price">Preço máx <input id="f-preco" type="range" min="0" max="10000" step="50" />
          <span id="f-preco-out"></span></label>
      </div>

      <table id="table">
        <thead>
          <tr>
            <th data-sort="destino">Rota</th>
            <th data-sort="data">Data</th>
            <th data-sort="cia">Cia</th>
            <th data-sort="preco">Preço</th>
            <th>Sinal</th>
            <th></th>
          </tr>
        </thead>
        <tbody id="rows"></tbody>
      </table>
      <p id="count" class="muted"></p>
    </section>
  </main>
  <script src="app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Create `web/style.css`**

```css
:root { font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; color: #1c1c1c; }
body { margin: 0; background: #fafafa; }
main { max-width: 1000px; margin: 0 auto; padding: 1.5rem 1rem; }
h1 { font-size: 1.25rem; font-weight: 600; }
.muted { color: #777; font-size: .8rem; }
.error { color: #b00020; }
#gate { max-width: 320px; margin: 4rem auto; text-align: center; }
#gate input, #gate button { font-size: 1rem; padding: .5rem .75rem; margin: .25rem; }
header { display: flex; align-items: baseline; justify-content: space-between; gap: 1rem; flex-wrap: wrap; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: .75rem; margin: 1rem 0; }
.card { background: #fff; border: 1px solid #eee; border-radius: 8px; padding: .75rem 1rem; }
.card .label { color: #777; font-size: .8rem; }
.card .value { font-size: 1.4rem; font-weight: 600; }
#filters { display: flex; flex-wrap: wrap; gap: .5rem; align-items: center; margin-bottom: 1rem; }
#filters select, #filters input[type=range] { font-size: .9rem; padding: .35rem; }
.check, .price { font-size: .85rem; color: #555; display: inline-flex; align-items: center; gap: .35rem; }
table { width: 100%; border-collapse: collapse; font-size: .9rem; background: #fff; }
th, td { text-align: left; padding: .5rem .6rem; border-bottom: 1px solid #eee; }
th { cursor: pointer; font-weight: 600; color: #555; font-size: .8rem; }
tr.alert { background: #eef5ff; }
.badge { font-size: .72rem; padding: 2px 8px; border-radius: 6px; margin-right: 4px; }
.badge.azul { background: #e6f1fb; color: #0c447c; }
.badge.watch { background: #e1f5ee; color: #085041; }
a.buy { color: #185fa5; text-decoration: none; }
```

- [ ] **Step 3: Create `web/app.js`**

```javascript
const b64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
let DEALS = [];

async function deriveKey(password, salt, iterations) {
  const base = await crypto.subtle.importKey("raw", new TextEncoder().encode(password), "PBKDF2", false, ["deriveKey"]);
  return crypto.subtle.deriveKey(
    { name: "PBKDF2", salt, iterations, hash: "SHA-256" },
    base, { name: "AES-GCM", length: 256 }, false, ["decrypt"]
  );
}

async function loadDeals(password) {
  const res = await fetch("deals.enc.json", { cache: "no-store" });
  const p = await res.json();
  const key = await deriveKey(password, b64(p.salt), p.iterations);
  const clear = await crypto.subtle.decrypt({ name: "AES-GCM", iv: b64(p.iv) }, key, b64(p.ciphertext));
  return JSON.parse(new TextDecoder().decode(clear));
}

function unique(arr) { return [...new Set(arr)].sort(); }
function fmtBRL(n) { return "R$ " + Math.round(n).toLocaleString("pt-BR"); }

function fillSelect(el, label, values) {
  el.innerHTML = `<option value="">${label}: todos</option>` +
    values.map((v) => `<option value="${v}">${v}</option>`).join("");
}

let sortKey = "preco", sortDir = 1;

function render() {
  const regiao = document.getElementById("f-regiao").value;
  const aeroporto = document.getElementById("f-aeroporto").value;
  const cia = document.getElementById("f-cia").value;
  const tipo = document.getElementById("f-tipo").value;
  const mes = document.getElementById("f-mes").value;
  const direto = document.getElementById("f-direto").checked;
  const precoMax = Number(document.getElementById("f-preco").value);
  document.getElementById("f-preco-out").textContent = fmtBRL(precoMax);

  let rows = DEALS.filter((d) =>
    (!regiao || d.regiao === regiao) &&
    (!aeroporto || d.destino === aeroporto) &&
    (!cia || d.cia === cia) &&
    (!mes || d.data.slice(0, 7) === mes) &&
    (!direto || d.direto) &&
    (!tipo || (tipo === "azul" ? d.azul_cheapest : d.price_watch != null)) &&
    d.preco <= precoMax
  );

  rows.sort((a, b) => {
    const x = a[sortKey], y = b[sortKey];
    return (x > y ? 1 : x < y ? -1 : 0) * sortDir;
  });

  document.getElementById("rows").innerHTML = rows.map((d) => {
    const badges =
      (d.azul_cheapest ? '<span class="badge azul">Azul</span>' : "") +
      (d.price_watch != null ? `<span class="badge watch">≤${Math.round(d.price_watch)}</span>` : "") || "—";
    const stops = d.direto ? "direto" : `${d.paradas} parada(s)`;
    const alert = d.azul_cheapest || d.price_watch != null ? ' class="alert"' : "";
    return `<tr${alert}>
      <td>${d.origem} → ${d.destino} <span class="muted">· ${d.regiao}</span></td>
      <td>${d.data}</td>
      <td>${d.cia} <span class="muted">· ${stops}</span></td>
      <td>${fmtBRL(d.preco)}</td>
      <td>${badges}</td>
      <td><a class="buy" href="${d.url_compra}" target="_blank" rel="noopener">comprar</a></td>
    </tr>`;
  }).join("");
  document.getElementById("count").textContent = `${rows.length} de ${DEALS.length} deals`;
}

function setup(data) {
  DEALS = data.deals;
  document.getElementById("updated").textContent = "atualizado: " + data.gerado_em;
  fillSelect(document.getElementById("f-regiao"), "Região", unique(DEALS.map((d) => d.regiao)));
  fillSelect(document.getElementById("f-aeroporto"), "Aeroporto", unique(DEALS.map((d) => d.destino)));
  fillSelect(document.getElementById("f-cia"), "Cia", unique(DEALS.map((d) => d.cia)));
  fillSelect(document.getElementById("f-mes"), "Mês", unique(DEALS.map((d) => d.data.slice(0, 7))));

  const maxPrice = Math.max(1000, ...DEALS.map((d) => d.preco));
  const slider = document.getElementById("f-preco");
  slider.max = String(Math.ceil(maxPrice / 50) * 50);
  slider.value = slider.max;

  document.querySelectorAll("#filters select, #filters input").forEach((el) =>
    el.addEventListener("input", render));
  document.querySelectorAll("th[data-sort]").forEach((th) =>
    th.addEventListener("click", () => {
      const k = th.dataset.sort;
      sortDir = sortKey === k ? -sortDir : 1;
      sortKey = k;
      render();
    }));

  document.getElementById("gate").hidden = true;
  document.getElementById("app").hidden = false;
  render();
}

async function unlock() {
  const pw = document.getElementById("password").value;
  const err = document.getElementById("error");
  err.hidden = true;
  try {
    setup(await loadDeals(pw));
  } catch (e) {
    err.hidden = false;
  }
}

document.getElementById("unlock").addEventListener("click", unlock);
document.getElementById("password").addEventListener("keydown", (e) => {
  if (e.key === "Enter") unlock();
});
```

- [ ] **Step 4: Verify manually in a browser**

Gere um arquivo cifrado de amostra e sirva localmente:

```bash
cd /c/FlightAlert
printf '{"gerado_em":"2026-06-18T11:03:00Z","deals":[{"origem":"CNF","destino":"GIG","regiao":"Rio de Janeiro","cia":"Azul","data":"2026-07-15","hora":"07h40","preco":289.0,"paradas":0,"direto":true,"url_compra":"https://www.google.com/travel/flights","azul_cheapest":true,"price_watch":null}]}' > deals.json
PANEL_PASSWORD=test123 python scripts/encrypt_deals.py
cp deals.enc.json web/
cd web && python -m http.server 8000
```

(No PowerShell, o env var é `$env:PANEL_PASSWORD="test123"; python scripts/encrypt_deals.py`.)

Abra `http://localhost:8000`:
- senha errada → mostra "Senha incorreta.";
- `test123` → aparece a tabela com 1 linha (CNF → GIG, R$ 289, badge "Azul", linha destacada), cards de resumo, filtros e ordenação por coluna funcionando.

Pare o servidor (Ctrl+C) e **apague a amostra** (não commitar):

```bash
rm /c/FlightAlert/web/deals.enc.json /c/FlightAlert/deals.json /c/FlightAlert/deals.enc.json
```

- [ ] **Step 5: Commit**

```bash
git add web/index.html web/style.css web/app.js
git commit -m "feat(panel): static web panel — password gate, decrypt, filterable table

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: Workflow — cifrar + publicar no GitHub Pages

**Files:**
- Modify: `.github/workflows/azul-alert.yml`

**Interfaces:**
- Consumes: `deals.json` (gerado por `main.py` via Task 3); `scripts/encrypt_deals.py` (Task 4); `web/` (Task 5); secret `PANEL_PASSWORD`.
- Produces: site publicado no GitHub Pages a cada run, sem commits no repo.

- [ ] **Step 1: Manual setup (GitHub, fora do código)**

1. Definir o secret da senha do painel:
   `gh secret set PANEL_PASSWORD --repo Vdto88/flight-alerts-bot` (digitar a senha quando pedir).
2. No repositório → Settings → Pages → "Build and deployment" → Source = **GitHub Actions**.

- [ ] **Step 2: Add permissions to the workflow**

Em `.github/workflows/azul-alert.yml`, logo abaixo do bloco `concurrency:` (antes de `jobs:`), adicione:

```yaml
permissions:
  contents: read
  pages: write
  id-token: write
```

- [ ] **Step 3: Add the github-pages environment to the job**

No job `run:`, logo abaixo de `timeout-minutes: 60`, adicione:

```yaml
    environment:
      name: github-pages
      url: ${{ steps.deploy.outputs.page_url }}
```

- [ ] **Step 4: Add build + deploy steps**

Ao final da lista de `steps:` (após o step "Run one pass"), adicione:

```yaml
      - name: Encrypt deals snapshot
        env:
          PANEL_PASSWORD: ${{ secrets.PANEL_PASSWORD }}
        run: python scripts/encrypt_deals.py

      - name: Assemble site
        run: |
          mkdir -p _site
          cp web/index.html web/style.css web/app.js _site/
          cp deals.enc.json _site/

      - name: Upload Pages artifact
        uses: actions/upload-pages-artifact@v3
        with:
          path: _site

      - name: Deploy to GitHub Pages
        id: deploy
        uses: actions/deploy-pages@v4
```

(Se `main.py` falhar, os steps seguintes não rodam — o site anterior permanece. Além disso, um step `Check snapshot is non-empty` verifica se `deals.json` tem pelo menos um deal: se o snapshot estiver vazio, os steps de cifrar/montar/publicar são pulados via `if: steps.snapshot.outputs.has_deals == 'true'` — o site anterior também permanece nesse caso.)

- [ ] **Step 5: Validate the workflow change**

Rode a suíte local para garantir que nada quebrou:
Run: `python -m pytest -q`
Expected: PASS (sem falhas).

Faça commit e push, depois dispare o workflow manualmente:

```bash
git add .github/workflows/azul-alert.yml
git commit -m "ci(panel): encrypt deals + deploy filterable panel to GitHub Pages

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
git push origin master
gh workflow run azul-alert.yml --repo Vdto88/flight-alerts-bot
```

- [ ] **Step 6: Confirm the deploy**

`gh run list --repo Vdto88/flight-alerts-bot --workflow azul-alert.yml` → o run mais recente conclui sem erro. Abra a URL do Pages (Settings → Pages, ou o output `page_url` do job), digite a senha do secret e confirme que a tabela carrega com os deals reais do run.

---

## Self-Review (preenchido)

**Spec coverage:**
- Painel completo (cheapest por rota+data) → Task 1 (`build_deals`).
- Snapshot serializado + timestamp → Task 2 (`write_deals`); gerado no ciclo → Task 3.
- JSON cifrado (AES-GCM + PBKDF2, params do spec) → Task 4.
- Front: gate de senha, decrypt WebCrypto, filtros (região/aeroporto/cia/tipo/mês/diretos/preço), ordenação, linhas de alerta, link comprar, "atualizado em" → Task 5.
- Deploy via artifact (master limpo), secret `PANEL_PASSWORD`, Pages = GitHub Actions, Telegram inalterado → Task 6 + Task 3 (zero query extra).
- `deals.json`/`deals.enc.json` gitignored → Task 3.
- Dep `cryptography` → Task 4.

**Placeholder scan:** sem TBD/TODO; todo step de código mostra o código completo.

**Type consistency:** `build_deals(flights, region, watches) -> list[dict]` (Task 1) é consumido com a mesma assinatura na Task 3; `write_deals(deals, path, generated_at=None)` (Task 2) idem; `encrypt_file`/`decrypt` (Task 4) batem com o formato lido pelo `app.js` (Task 5) e pelo step de cifrar (Task 6). Chaves do dict de deal idênticas entre Task 1, o teste da Task 3 e o `app.js`.
