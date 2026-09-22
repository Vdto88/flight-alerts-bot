# Round Trips by Stay Length — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the owner pick a stay length in the new panel and see every outbound fare paired with the cheapest return that many days later, priced as a total.

**Architecture:** The server publishes one small table (`estadias`: valid stays per country) in the existing snapshot. The browser already holds every one-way fare in both directions, so the new panel indexes the returns once and pairs them on the fly. A single `viewDeals()` step turns outbound records into "paired" records whose `preco` is the total; filtering, sorting, the highlights board and the counters then work unchanged. Rendering adds the return line, the unpaired notice and a table column.

**Tech Stack:** Python 3.11 + pytest (server side); vanilla JS/CSS (new panel, no build step, no JS test runner).

**Spec:** `docs/superpowers/specs/2026-09-22-panel-stay-pairing-design.md`

## Global Constraints

- Stays: Brasil `(4, 5, 6, 7)`; Argentina and Chile `(7, 8, 9, 10)`; every other country `(13, 14, 15, 16)`.
- Snapshot field exactly: `"estadias": {"por_pais": {...}, "padrao": [...]}` (lists, ascending).
- Default selector value is "Só ida", which must render exactly today's panel.
- Only the new panel changes (`web/index.html`, `web/app.js`, `web/style.css`). `web/classic/` is untouched. No change to Telegram, alerts, search or history.
- No new dependency. Code and comments in English; every visible string in Portuguese.
- Airline and other snapshot text reaches the DOM only through the existing `esc()` helper.
- Run Python tests only as `timeout 100 python -m pytest -q` (370 tests today, must stay green).
- **Git Bash heredoc trap on this PC:** a double backslash inside `python - <<'EOF'` collapses and an escaped `\n` becomes a real line break; long heredocs with backticks also fail to parse. Create and edit files with the Write/Edit tools, never through a heredoc.
- Never `git push`. Commit on branch `feat/panel-stay-pairing`; end every commit message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Do not stage `docs/superpowers/*/2026-04-16-*` (untracked, owner's decision pending), `_site/` or `.claude/` (git-ignored).

## Rulings made while planning (they refine the spec; the spec is updated to match)

1. In a pass (one card per destination), dates without a return are dropped from that pass. A pass left with no paired date stays visible, dimmed, with the reason, and sorts last.
2. The invalid-stay text names the destination's country (`Portugal`, `Chile`) or "destinos nacionais"; the snapshot has no "Europa" label.
3. The table gains one column, "Volta" (date · airline · price · stay), shown only with a stay chosen; the "Tarifa" column shows the total with the outbound price beside it.
4. With the price slider at its maximum there is no price limit (totals can exceed the one-way maximum the slider was sized for).
5. The return line sits between the pass's button and its foot, because a link cannot live inside the pass `<button>`.

## File Structure

| File | Change |
|---|---|
| `config.py` | `STAY_OPTIONS`, `STAY_OPTIONS_DEFAULT` |
| `panel.py` | `write_deals` ships `estadias` |
| `tests/test_panel.py`, `tests/test_airports.py` | new tests |
| `web/index.html` | `#f-estadia` selector (Task 2); "Volta" table header (Task 3) |
| `web/app.js` | pairing state, `pairReturn`, `viewDeals`, wiring (Task 2); rendering (Task 3) |
| `web/style.css` | return line, dimmed pass, hidden table column (Task 3) |
| `_site/make_pairing_fixture.py` | throwaway fixture builder (git-ignored, never committed) |

---

### Task 1: Stay table in config and snapshot

**Files:**
- Modify: `config.py` (insert right after the closing `}` of `AIRPORTS`)
- Modify: `panel.py` (import line 10; `write_deals` payload)
- Test: `tests/test_panel.py`, `tests/test_airports.py`

**Interfaces:**
- Produces: `config.STAY_OPTIONS: dict[str, tuple[int, ...]]`, `config.STAY_OPTIONS_DEFAULT: tuple[int, ...]`; snapshot key `estadias` = `{"por_pais": {country: [days...]}, "padrao": [days...]}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_panel.py`:

```python
def test_write_deals_ships_the_stay_table_for_round_trip_pairing(tmp_path):
    out = tmp_path / "deals.json"
    panel.write_deals([], str(out))
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["estadias"] == {
        "por_pais": {"Brasil": [4, 5, 6, 7], "Argentina": [7, 8, 9, 10], "Chile": [7, 8, 9, 10]},
        "padrao": [13, 14, 15, 16],
    }
```

Append to `tests/test_airports.py`:

```python
def test_every_destination_country_gets_a_deliberate_stay_range():
    countries = {a.pais for code, a in config.AIRPORTS.items() if code != config.AZUL_HUB}
    assert set(config.STAY_OPTIONS) <= countries
    # Europe takes the long default on purpose. A new country would land here silently,
    # so this list must be edited by hand when one is added: decide its stays then.
    assert countries - set(config.STAY_OPTIONS) == {"Portugal", "Espanha", "Itália", "França"}


def test_stay_ranges_are_ascending_and_positive():
    for days in [*config.STAY_OPTIONS.values(), config.STAY_OPTIONS_DEFAULT]:
        assert list(days) == sorted(set(days)) and days[0] > 0
```

- [ ] **Step 2: Run them and watch them fail**

Run: `timeout 100 python -m pytest tests/test_panel.py tests/test_airports.py -q`
Expected: 3 failures (`KeyError: 'estadias'`, `AttributeError: module 'config' has no attribute 'STAY_OPTIONS'`).

- [ ] **Step 3: Implement**

In `config.py`, right after the closing `}` of `AIRPORTS`, insert:

```python

# Stays offered by the new panel's round-trip selector, by country of the non-hub airport.
# The panel pairs each outbound fare with the cheapest return this many days later.
# Ascending order matters: on equal totals the panel keeps the shorter stay.
STAY_OPTIONS: dict[str, tuple[int, ...]] = {
    "Brasil":    (4, 5, 6, 7),
    "Argentina": (7, 8, 9, 10),
    "Chile":     (7, 8, 9, 10),
}
STAY_OPTIONS_DEFAULT: tuple[int, ...] = (13, 14, 15, 16)   # any other country (Europe today)
```

In `panel.py`, change the import line

```python
from config import AIRPORTS, AZUL_HUB, PriceWatch, WINDOW_MAX_DAYS
```

to

```python
from config import (AIRPORTS, AZUL_HUB, PriceWatch, STAY_OPTIONS, STAY_OPTIONS_DEFAULT,
                    WINDOW_MAX_DAYS)
```

and in `write_deals`, add this entry to `payload` right after the `"aeroportos"` line:

```python
        # Stays the new panel's round-trip selector offers, per country of the destination.
        "estadias": {"por_pais": {k: list(v) for k, v in STAY_OPTIONS.items()},
                     "padrao": list(STAY_OPTIONS_DEFAULT)},
```

- [ ] **Step 4: Run the tests and the full suite**

Run: `timeout 100 python -m pytest tests/test_panel.py tests/test_airports.py -q`, then `timeout 100 python -m pytest -q`
Expected: all pass (373).

- [ ] **Step 5: Commit**

```bash
git add config.py panel.py tests/test_panel.py tests/test_airports.py
git commit -m "feat(panel): ship the stay table for round-trip pairing

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Pairing in the panel (data flow and selector)

**Files:**
- Modify: `web/index.html` (after the `#f-ordem` `</select>`)
- Modify: `web/app.js` (globals, helpers, `filtered`, `groupDeals`, `sortGroups`, `renderBoard`, `boardRow`, `renderCounters`, `renderTable`, `render`, `setup`)
- Create (git-ignored, not committed): `_site/make_pairing_fixture.py`

**Interfaces:**
- Consumes: snapshot `estadias` (Task 1); one-way records with `origem`, `destino`, `data`, `preco`, `cia`, `url_compra`, `pais`; `HUB`, `isRT`, `sentidoOf`, `DEALS`, `esc`, `fmtBRL`, `fmtShort`, `scheduleRender`, `tableLimit`, `TABLE_PAGE` already in `app.js`.
- Produces (Task 3 relies on these exact names):
  - globals `ESTADIAS` (object or `null`), `RETURNS` (`Map` of `"<origem>|<data>"` → return record), `STAY` (`""`, `"best"` or a number as a string);
  - `pairReturn(ida, stay, index, estadias)` → `{volta, total, estadia}` or `{motivo: "invalid-stay" | "out-of-window", validas}`;
  - `viewDeals()` → the rows the panel lists;
  - paired view record: the outbound record plus `preco` (= total), `preco_ida`, `par_volta` (the return record), `par_estadia` (days);
  - unpaired view record: the outbound record plus `sem_par` (the motivo) and `validas` (array of days);
  - group field `g.unpaired` (an unpaired record) on a pass with no paired date.

- [ ] **Step 1: Selector markup**

In `web/index.html`, right after the closing `</select>` of `<select id="f-ordem" …>`, insert:

```html
          <select id="f-estadia" aria-label="Estadia para ida e volta" hidden>
            <option value="">Estadia: só ida</option>
            <option value="best">Estadia: melhor volta</option>
          </select>
```

(The day options are added by `setup()` from the snapshot. `#f-estadia` sits outside `#filters` on purpose: "Limpar" does not reset a viewing mode, and the generic filter listener does not bind it.)

- [ ] **Step 2: State and pure helpers**

In `web/app.js`, right after the line `let NEAR_DAYS = 120;`, insert:

```js
// Round trips by stay (config.STAY_OPTIONS, shipped as "estadias"). STAY: "" = one-way view,
// "best" = cheapest return over the destination's stays, else a number of days as a string.
let ESTADIAS = null;
let RETURNS = new Map();          // "<origem>|<data>" -> one-way return record (X -> HUB)
let STAY = "";
let VIEW_CACHE = null;            // [STAY, rows]: pairing depends on STAY only
const STAY_KEY = "painel-estadia";
```

Right after the `groupKey` definition (the statement ending in `` : `${cidadeOf(d)}|${sentidoOf(d)}`); ``), insert:

```js

/* ---------------- Round trips by stay ---------------- */
const addDays = (iso, n) => {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + n)).toISOString().slice(0, 10);
};
const staysFor = (d, estadias) => estadias.por_pais[d.pais] || estadias.padrao;

/* The cheapest return `stay` days after an outbound one-way fare. `stay` is a number, or
   "best" for every valid stay of the destination (ties keep the shorter stay, because the
   stays arrive in ascending order and only a strictly cheaper return replaces the best).
   -> {volta, total, estadia} | {motivo: "invalid-stay" | "out-of-window", validas} */
function pairReturn(ida, stay, index, estadias) {
  const validas = staysFor(ida, estadias);
  const tries = stay === "best" ? validas : validas.includes(stay) ? [stay] : null;
  if (!tries) return { motivo: "invalid-stay", validas };
  let best = null;
  for (const s of tries) {
    const volta = index.get(`${ida.destino}|${addDays(ida.data, s)}`);
    if (volta && (!best || volta.preco < best.volta.preco)) best = { volta, estadia: s };
  }
  if (!best) return { motivo: "out-of-window", validas };
  return { ...best, total: Math.round((ida.preco + best.volta.preco) * 100) / 100 };
}

/* What the panel lists. One-way view: the snapshot as is. With a stay chosen: only outbound
   one-way fares, each carrying its return (its price becomes the total) or why it has none.
   Returns and the Europe watch's round trips would duplicate the pairs, so they drop out. */
function viewDeals() {
  if (!STAY || !ESTADIAS) return DEALS;
  if (VIEW_CACHE && VIEW_CACHE[0] === STAY) return VIEW_CACHE[1];
  const stay = STAY === "best" ? "best" : Number(STAY);
  const rows = DEALS.filter((d) => !isRT(d) && sentidoOf(d) === "ida").map((d) => {
    const r = pairReturn(d, stay, RETURNS, ESTADIAS);
    return r.volta
      ? { ...d, preco: r.total, preco_ida: d.preco, par_volta: r.volta, par_estadia: r.estadia }
      : { ...d, sem_par: r.motivo, validas: r.validas };
  });
  VIEW_CACHE = [STAY, rows];
  return rows;
}
```

- [ ] **Step 3: Route every consumer through the view**

In `filtered()`:
- replace `return DEALS.filter((d) =>` with `return viewDeals().filter((d) =>`;
- replace the last condition `d.preco <= f.precoMax` with

```js
    // Unpaired fares have no total to compare; the slider at its maximum means no limit,
    // since totals can exceed the one-way maximum it was sized for.
    (d.sem_par || f.precoMax >= Number($("f-preco").max) || d.preco <= f.precoMax)
```

In `groupDeals(rows)`, replace the line `g.deals.sort((a, b) => (a.data < b.data ? -1 : 1));` (the first line inside `for (const g of groups.values()) {`) with:

```js
    // With a stay chosen, dates without a return drop out of their pass; a pass left with
    // none stays, dimmed, to say why (wrong stay for this destination, or no return yet).
    const paired = g.deals.filter((d) => !d.sem_par);
    if (paired.length) g.deals = paired;
    else g.unpaired = g.deals[0];
    g.deals.sort((a, b) => (a.data < b.data ? -1 : 1));
```

In `sortGroups`, replace the `return` line with:

```js
  return groups.sort((a, b) =>
    (!!a.unpaired - !!b.unpaired) || (pick(a) > pick(b) ? 1 : pick(a) < pick(b) ? -1 : 0));
```

In `renderBoard(rows)`, insert as the first line of the function body:

```js
  rows = rows.filter((d) => !d.sem_par);   // an unpaired fare is no highlight
```

In `boardRow(d)`, replace `const leg = isRT(d) ? "ida+volta" : sentidoOf(d);` with:

```js
  const leg = isRT(d) ? "ida+volta" : d.par_volta ? `ida+volta ${d.par_estadia}d` : sentidoOf(d);
```

In `renderCounters(rows)`, replace the `const menor = …` line with:

```js
  const priced = rows.filter((d) => !d.sem_par);
  const menor = priced.length ? fmtBRL(Math.min(...priced.map((d) => d.preco))) : "—";
```

In `renderTable(rows)`, replace the sort comparator so unpaired rows go last:

```js
  const sorted = [...rows].sort((a, b) => {
    const x = a[sortKey] ?? Infinity, y = b[sortKey] ?? Infinity;
    return (!!a.sem_par - !!b.sem_par) || (x > y ? 1 : x < y ? -1 : 0) * sortDir;
  });
```

In `render()`, replace `${fmtInt(DEALS.length)}` with `${fmtInt(viewDeals().length)}`.

- [ ] **Step 4: Wire the selector in `setup()`**

In `setup(data)`, right after the line `$("hub-city").textContent = cityOf(HUB);`, insert:

```js

  // Round trips by stay: returns are indexed once (sentidoOf needs HUB, set just above), and
  // the selector lists every stay any country uses. A snapshot without the table hides it.
  ESTADIAS = data.estadias || null;
  RETURNS = new Map(DEALS.filter((d) => !isRT(d) && sentidoOf(d) === "volta")
    .map((d) => [`${d.origem}|${d.data}`, d]));
  VIEW_CACHE = null;
  const stayEl = $("f-estadia");
  if (ESTADIAS) {
    const days = [...new Set([...Object.values(ESTADIAS.por_pais).flat(), ...ESTADIAS.padrao])]
      .sort((a, b) => a - b);
    stayEl.insertAdjacentHTML("beforeend",
      days.map((n) => `<option value="${n}">Estadia: ${n} dias</option>`).join(""));
    let saved = "";
    try { saved = localStorage.getItem(STAY_KEY) || ""; } catch (e) { /* storage blocked: one-way */ }
    if ([...stayEl.options].some((o) => o.value === saved)) { stayEl.value = saved; STAY = saved; }
    stayEl.hidden = false;
    stayEl.addEventListener("input", () => {
      STAY = stayEl.value;
      try { localStorage.setItem(STAY_KEY, STAY); } catch (e) { /* applied, just not remembered */ }
      tableLimit = TABLE_PAGE;
      scheduleRender();
    });
  }
```

- [ ] **Step 5: Fixture builder**

Write `_site/make_pairing_fixture.py` with the Write tool (it creates `_site/` if missing), then run `python _site/make_pairing_fixture.py` from the repo root:

```python
"""Throwaway: encrypted fixture for the stay-pairing browser checks. Password teste123."""
import json
import shutil
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import panel  # noqa: E402
from scripts.encrypt_deals import encrypt_bytes  # noqa: E402

site = Path("_site")
site.mkdir(exist_ok=True)
for name in ("index.html", "style.css", "app.js", "switch.js"):
    shutil.copy(Path("web") / name, site / name)

BASE = date.today() + timedelta(days=40)


def rec(orig, dest, day, price, cia="Azul"):
    other = dest if orig == "CNF" else orig
    return {"origem": orig, "destino": dest, "regiao": other, "cia": cia,
            "data": (BASE + timedelta(days=day)).isoformat(), "hora": "08h00",
            "preco": float(price), "paradas": 0, "direto": True,
            "url_compra": f"https://www.google.com/travel/flights?{orig}-{dest}-{day}",
            "azul_cheapest": False, "price_watch": None, **panel.place_fields(other)}


deals = []
# Rio: outbound days 0-9, returns days 0-20. Return price = 300 + day, so for any outbound the
# cheapest return in 4-7 days is the 4-day one, and a 5-day stay from day 0 costs 305.
deals += [rec("CNF", "GIG", i, 250 + 10 * i) for i in range(10)]
deals += [rec("GIG", "CNF", i, 300 + i, cia="Gol") for i in range(21)]
# Lisbon: outbound days 0-5, returns days 10-25; the return price falls with the day, so
# "best" picks the 16-day stay.
deals += [rec("CNF", "LIS", i, 2000 + 50 * i, cia="TAP") for i in range(6)]
deals += [rec("LIS", "CNF", i, 2600 - 10 * i, cia="TAP") for i in range(10, 26)]
# Bariloche: outbound days 0-3, returns days 5-15; from day 0 the cheapest return is on day 9.
deals += [rec("CNF", "BRC", i, 1200, cia="Latam") for i in range(4)]
deals += [rec("BRC", "CNF", i, 900 if i == 9 else 1100, cia="Latam") for i in range(5, 16)]
# São Luís: outbound only, so every stay is "out of the window".
deals += [rec("CNF", "SLZ", i, 700) for i in range(3)]
# One Europe-watch round trip, visible only in the one-way view.
ida_day = (BASE + timedelta(days=1)).isoformat()
deals.append({**rec("CNF", "LIS", 1, 3900), "tipo": "roundtrip", "data_ida": ida_day,
              "ida_origem": "CNF", "ida_destino": "LIS", "cia_ida": "TAP", "preco_ida": 2000.0,
              "url_ida": "https://example.com/ida", "volta_origem": "OPO", "volta_destino": "CNF",
              "data_volta": (BASE + timedelta(days=15)).isoformat(), "cia_volta": "TAP",
              "preco_volta": 1900.0, "url_volta": "https://example.com/volta", "estadia": 14,
              "max_total": 3000.0})

out = site / "deals.json"
panel.write_deals(deals, str(out), generated_at=datetime.now(timezone.utc))
(site / "deals.enc.json").write_text(
    json.dumps(encrypt_bytes(out.read_bytes(), "teste123")), encoding="utf-8")
out.unlink()
print(f"fixture pronta em _site/ ({len(deals)} registros, base {BASE})")
```

- [ ] **Step 6: Check the data flow in the browser**

Create `.claude/launch.json` if it does not exist (it is git-ignored):
`{"version":"0.0.1","configurations":[{"name":"panel-fixture","runtimeExecutable":"python","runtimeArgs":["-m","http.server","8765","--directory","_site"],"port":8765}]}`
Start it with the browser preview (`preview_start` name `panel-fixture`), unlock with `teste123` (if clicking is unreliable, fill the password and call `document.getElementById("gate-form").requestSubmit()`), then evaluate in the page:

```js
const ida0 = (dst) => DEALS.find((d) => d.origem === "CNF" && d.destino === dst && !d.tipo);
[
  pairReturn(ida0("GIG"), 5, RETURNS, ESTADIAS).total,          // 250 + 305 = 555
  pairReturn(ida0("GIG"), "best", RETURNS, ESTADIAS).estadia,   // 4
  pairReturn(ida0("LIS"), 5, RETURNS, ESTADIAS).motivo,         // "invalid-stay"
  pairReturn(ida0("LIS"), "best", RETURNS, ESTADIAS).estadia,   // 16
  pairReturn(ida0("BRC"), "best", RETURNS, ESTADIAS).estadia,   // 9
  pairReturn(ida0("SLZ"), 5, RETURNS, ESTADIAS).motivo,         // "out-of-window"
]
```

Expected: `[555, 4, "invalid-stay", 16, 9, "out-of-window"]`. Then choose "Estadia: 5 dias" and confirm: the count line drops to outbound fares only; the highlights board lists only paired fares; the Rio pass sorts first; the São Luís and Lisbon passes come last. Choose "Estadia: só ida" and confirm the round-trip record and the return passes are back. Reload and unlock again: the last choice is restored. (Passes do not show the return line yet — that is Task 3.) Report each check in your report file.

- [ ] **Step 7: Run the Python suite and commit**

Run: `timeout 100 python -m pytest -q` (unchanged, still green).

```bash
git add web/index.html web/app.js
git commit -m "feat(panel): pair outbound fares with a return by chosen stay

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Rendering the pairs (passes, calendar, table, styles)

**Files:**
- Modify: `web/app.js` (`spark`, `calendar`, `datesTable`, `passHTML`, `tableRowHTML`, `render`; two new helpers)
- Modify: `web/index.html` (table header)
- Modify: `web/style.css` (append)

**Interfaces:**
- Consumes (from Task 2): `STAY`, `ESTADIAS`, `viewDeals`; paired records (`preco` = total, `preco_ida`, `par_volta`, `par_estadia`); unpaired records (`sem_par`, `validas`); `g.unpaired`.
- Produces: nothing other tasks rely on.

- [ ] **Step 1: Wording helpers**

In `web/app.js`, right after the `viewDeals` function, insert:

```js

/* Why an outbound fare has no return in the chosen stay. */
function unpairedText(d) {
  if (d.sem_par === "out-of-window") return "Volta fora da janela buscada";
  const where = d.pais === "Brasil" ? "destinos nacionais" : d.pais;
  return `Estadia de ${STAY} dias não vale para ${where} (${d.validas[0]}–${d.validas[d.validas.length - 1]} dias)`;
}

/* The return leg, as a link to buy it. */
const returnLink = (d) =>
  `<a href="${esc(d.par_volta.url_compra)}" target="_blank" rel="noopener">${fmtShort(d.par_volta.data)} · ${esc(d.par_volta.cia)} · ${fmtBRL(d.par_volta.preco)}</a>`;
```

- [ ] **Step 2: Sparkline keeps the outbound leg's price**

In `spark(d)`, insert as the first line of the body:

```js
  const today = d.preco_ida ?? d.preco;   // a paired pass shows a total; the series is the outbound leg's
```

and replace the three uses of `d.preco` inside the function (`d.spark.concat(d.preco)`, `até ${fmtBRL(d.preco)} hoje`, `cy="${y(d.preco).toFixed(1)}"`) with `today`. Move the `if (!d.spark || d.spark.length < 2) return "";` guard above the new line if you prefer; either order works.

- [ ] **Step 3: Calendar and dates table**

In `calendar(g)`, in the `title="…"` of each day link, insert right after `${esc(d.cia)}`:

```js
${d.par_volta ? ` · volta ${fmtShort(d.par_volta.data)} ${fmtBRL(d.par_volta.preco)}` : ""}
```

and replace the legend's last span `<span>Contorno âmbar = melhor dia. Toque no dia para comprar.</span>` with:

```js
<span>${g.best.par_volta ? "Valores = ida + volta. " : ""}Contorno âmbar = melhor dia. Toque no dia para comprar.</span>
```

Replace the whole `datesTable(g)` function with:

```js
function datesTable(g) {
  const paired = !!g.best.par_volta;
  const rows = g.deals.map((d) => `<tr>
    <td class="num">${fmtDate(d.data)}</td>
    <td>${esc(d.cia)}</td>
    <td>${d.direto ? "direto" : `${d.paradas} parada(s)`}</td>
    ${paired ? `<td class="num">${returnLink(d)} <span class="muted">· ${d.par_estadia} d</span></td>` : ""}
    <td class="num"><a class="buy" href="${esc(d.url_compra)}" target="_blank" rel="noopener">${fmtBRL(d.preco)}</a></td>
  </tr>`).join("");
  return `<table class="dates"><tr><th>Data</th><th>Cia</th><th>Voo</th>${paired ? "<th>Volta</th>" : ""}<th>${paired ? "Total" : "Tarifa"}</th></tr>${rows}</table>`;
}
```

- [ ] **Step 4: The pass**

In `passHTML(g, i)`, replace the `const meta = g.rt ? … : …;` statement with:

```js
  const meta = g.rt
    ? [["Ida", fmtShort(d.data_ida)], ["Volta", fmtShort(d.data_volta)], ["Estadia", `${d.estadia} dias`]]
    : d.par_volta
      ? [["Ida", fmtShort(d.data)], ["Volta", fmtShort(d.par_volta.data)], ["Estadia", `${d.par_estadia} dias`]]
      : [["Melhor dia", fmtShort(d.data)], ["Cia", d.cia], ["Datas", g.deals.length]];
  // Between the pass's button and its foot: a link cannot live inside the <button>.
  const returnLine = d.par_volta
    ? `<div class="pass-return">↩️ Volta ${returnLink(d)} <span>· ${d.par_estadia} dias</span></div>`
    : g.unpaired ? `<div class="pass-return is-missing">${esc(unpairedText(g.unpaired))}</div>` : "";
```

In the returned template:
- `<article class="pass ${g.alert ? "is-alert" : ""} ${open ? "open" : ""}"` becomes `<article class="pass ${g.alert ? "is-alert" : ""} ${open ? "open" : ""} ${g.unpaired ? "is-unpaired" : ""}"`;
- `Tarifa${g.rt ? " total" : ""}` becomes `Tarifa${g.rt ? " total" : d.par_volta ? " ida + volta" : g.unpaired ? " só ida" : ""}`;
- the line `${delta(d) || (g.rt ? "" : rotaDelta(d) || '<span class="delta flat">sem histórico</span>')}` becomes

```js
        ${d.par_volta
          ? `<span class="delta flat">ida ${fmtBRL(d.preco_ida)} + volta ${fmtBRL(d.par_volta.preco)}</span>`
          : delta(d) || (g.rt ? "" : rotaDelta(d) || '<span class="delta flat">sem histórico</span>')}
```

- insert `${returnLine}` on its own line between `</button>` and `<div class="pass-foot">`.

- [ ] **Step 5: The table**

In `web/index.html`, in the table header, insert right after the `Tarifa` `<th>` line:

```html
                <th class="col-pair">Volta</th>
```

In `tableRowHTML(d)`, replace the Tarifa cell line `${cell("Tarifa", `<span class="num">${fmtBRL(d.preco)}</span>`)}` with:

```js
    ${cell("Tarifa", `<span class="num">${fmtBRL(d.preco)}</span>${d.par_volta ? ` <span class="muted">ida ${fmtBRL(d.preco_ida)}</span>` : ""}`)}
    <td data-label="Volta" class="col-pair">${d.par_volta
      ? `${returnLink(d)} <span class="muted">· ${d.par_estadia} d</span>`
      : d.sem_par ? `<span class="muted">${esc(unpairedText(d))}</span>` : "—"}</td>
```

In `render()`, insert as the first line of the body:

```js
  $("table").classList.toggle("no-pair", !STAY || !ESTADIAS);
```

- [ ] **Step 6: Styles**

Append to `web/style.css`:

```css

/* ---------------- Round trips by stay ---------------- */
.pass-return {
  display: flex; flex-wrap: wrap; align-items: baseline; gap: var(--sp-2);
  padding: var(--sp-2) var(--sp-4);
  border-top: 1px dashed var(--line);
  font-family: var(--f-mono); font-size: .75rem; color: var(--text-2);
}
.pass-return a { color: var(--violet); text-decoration: none; }
.pass-return a:hover, .pass-return a:focus-visible { text-decoration: underline; }
.pass-return.is-missing { color: var(--text-3); }
.pass.is-unpaired { opacity: .55; }
.pass.is-unpaired:hover, .pass.is-unpaired:focus-within { opacity: .8; }
#table.no-pair .col-pair { display: none; }
```

- [ ] **Step 7: Verify in the browser**

Rebuild the fixture (`python _site/make_pairing_fixture.py`, which re-copies `web/`), serve it (`panel-fixture`), unlock with `teste123`, and check at desktop width and with the mobile preset (375 px):

1. "Só ida": identical to the current panel — return passes (e.g. "GIG → CNF") and the Europe round-trip pass present, no return lines, no "Volta" table column.
2. "Estadia: 5 dias": only outbound passes. The Rio pass shows fare 555, label "Tarifa ida + volta", "ida R$ 250 + volta R$ 305", meta Ida/Volta/Estadia 5 dias, and the line "↩️ Volta <date> · Gol · R$ 305 · 5 dias" whose link opens the return's URL.
3. Same stay: the Lisbon pass is dimmed, reads "Estadia de 5 dias não vale para Portugal (13–16 dias)", label "Tarifa só ida", and sorts after the paired passes.
4. "Estadia: melhor volta": Lisbon pairs a 16-day stay, Bariloche 9, Rio 4.
5. São Luís (any stay): dimmed, "Volta fora da janela buscada".
6. Open the Rio pass: the calendar legend starts "Valores = ida + volta."; the dates table has "Volta" and "Total" columns.
7. Table view with a stay: "Volta" column present, Tarifa shows the total plus "ida R$ …"; unpaired rows last with their reason. Back to "Só ida": the column disappears.
8. Slider "Até R$" at maximum keeps every pair; lowered to R$ 600 keeps only the Rio pairs at or under it (plus the unpaired passes).
9. At 375 px: no horizontal scroll (`document.documentElement.scrollWidth === document.documentElement.clientWidth`), the return line wraps under the pass.

Report each check in your report file.

- [ ] **Step 8: Run the Python suite and commit**

Run: `timeout 100 python -m pytest -q` (still green).

```bash
git add web/index.html web/app.js web/style.css
git commit -m "feat(panel): show the paired return, unpaired reasons and a Volta column

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## After the last task

Merge into `master` with `--no-ff` and push only when the owner authorises. After the next main-workflow deploy, check one national and one European destination in the real panel with a stay chosen.
