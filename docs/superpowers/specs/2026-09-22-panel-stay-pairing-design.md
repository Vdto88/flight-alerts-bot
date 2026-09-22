# Round trips by stay length in the panel — design

Date: 2026-09-22
Status: approved in chat, pending spec review
Branch: `feat/panel-stay-pairing`

## Problem

The panel shows one-way fares. The owner wants to see an outbound fare together with the
cheapest return a fixed number of days later, and to pick that number himself. There is no
return date to search for, but the bot already searches both directions (CNF→X and X→CNF) for
every airport and every date of the window, so every return fare is already in the snapshot.
Pairing them costs no extra query.

Decisions the owner made in chat:

1. Panel only. No new Telegram message and no change to existing alerts.
2. A stay selector in the new panel: "Só ida", "Melhor", or an exact number of days.
3. Stays per destination: Brazil 4, 5, 6, 7 days; Patagonia (Argentina, Chile) 7, 8, 9, 10;
   Europe 13, 14, 15, 16.
4. Pairing happens in the browser (approach 1); the server only publishes the stay table.

## Out of scope

- Telegram alerts for pairs, price ceilings for pairs.
- Price history of pairs (the sparkline stays the outbound leg's).
- Open-jaw pairs (return from another airport of the same region). The Europe round-trip
  watch keeps doing that on its own.
- The classic panel.
- Searching dates beyond the current window to find missing returns.

## 1. Data and config

`config.py`:

```python
# Stays offered by the panel's round-trip selector, by country of the non-hub airport.
STAY_OPTIONS: dict[str, tuple[int, ...]] = {
    "Brasil":    (4, 5, 6, 7),
    "Argentina": (7, 8, 9, 10),
    "Chile":     (7, 8, 9, 10),
}
STAY_OPTIONS_DEFAULT: tuple[int, ...] = (13, 14, 15, 16)   # any other country (Europe today)
```

`panel.write_deals` adds one top-level field to the snapshot:

```json
"estadias": {"por_pais": {"Brasil": [4, 5, 6, 7], "Argentina": [7, 8, 9, 10],
                           "Chile": [7, 8, 9, 10]},
             "padrao": [13, 14, 15, 16]}
```

Nothing else changes on the server. One-way records already carry `origem`, `destino`, `data`,
`preco`, `cia`, `url_compra` and `pais` (the non-hub airport's country). Far-band records
carried from the long cycle (`visto_em`) take part in pairing like any other record.

Known limit: a return exists only inside the searched window (120 days on short cycles, 180
with the carried far band). An outbound near the end of the window may have no return; the
card says so instead of hiding the outbound.

## 2. Panel behaviour (`web/index.html`, `web/app.js`, `web/style.css`)

**Selector.** A new `<select id="f-estadia">` in the toolbar, next to "Ordenar":
`Só ida · Melhor · 4 · 5 · 6 · 7 · 8 · 9 · 10 · 13 · 14 · 15 · 16 dias`. Default "Só ida",
which renders exactly today's panel. The choice is remembered in `localStorage` under its own
key (the other filters are not persisted today; this one is, because it is a viewing mode),
every access wrapped in try/catch.

**Return index.** Built once in `setup()`: a `Map` from `"<origem>|<data>"` to the one-way
record of every return (`destino === HUB`).

**Pure pairing function.**

```js
// -> {volta, total, estadia} | {motivo: "invalid-stay" | "out-of-window", validas}
function pairReturn(ida, stay, index, estadias)
```

- `validas` = `estadias.por_pais[ida.pais] || estadias.padrao`.
- Exact stay not in `validas` → `{motivo: "invalid-stay", validas}`.
- Exact stay: return = `index.get(ida.destino + "|" + (ida.data + stay days))`; missing →
  `{motivo: "out-of-window", validas}`.
- "Melhor": the cheapest return over `validas`; ties go to the shorter stay; none found →
  `"out-of-window"`.
- `total = ida.preco + volta.preco`, rounded to cents.

**With a stay selected ("Melhor" or a number):**
- Only outbound one-way records are listed. Return records and the Europe watch's `roundtrip`
  records are hidden (they would duplicate the pairs).
- Each paired card shows the total as its big price, a line "ida R$ 340 + volta R$ 380", and a
  return line "↩️ Volta 19/11 · 5 dias · Gol · R$ 380" whose link opens the return's
  `url_compra`. The outbound link stays where it is.
- Unpaired cards stay visible, dimmed, with "estadia de 5 dias não vale para Europa (13–16)"
  (label from the record's `pais`/region and `validas`) or "volta fora da janela". They sort
  after every paired card and are ignored by the price filter and the highlights board.
- Price filter ("Até R$"), price sort, the "Em destaque agora" board and the counters use the
  total for paired cards.
- The table view gains two columns, "Volta" (date · airline) and "Total".
- Signal badges (Azul mais barata, alerta de preço) keep describing the outbound leg.

**Mobile (375 px).** The selector is a `<select>` like the other filters; the return line
wraps below the price. No horizontal scroll.

**Third-party text.** Airline names already go through the panel's escaping (`esc`); the new
markup uses the same helper.

## 3. Tests and verification

Python (pytest, run as `timeout 100 python -m pytest -q`):
- `tests/test_panel.py`: the snapshot carries `estadias` equal to the config.
- `tests/test_airports.py`: every country in `AIRPORTS` other than the hub's is either a key of
  `STAY_OPTIONS` or deliberately on the default; the test lists the countries on the default
  (`Portugal`, `Espanha`, `Itália`, `França`) so adding an Argentine airport cannot silently
  get European stays.

Browser (no JS test runner): encrypted fixture in `_site/`, `python -m http.server` through
`.claude/launch.json`, password `teste123`, desktop and 375 px:
1. "Só ida" renders the same cards as before (returns and round-trip records present).
2. Stay 5: only outbounds; a GIG card shows the return on `data + 5`, total = sum, sorted by
   total.
3. Stay 5 on a Lisbon card: "não vale para Europa (13–16)", dimmed, after the paired cards.
4. "Melhor": Lisbon picks the cheapest of 13–16, Bariloche of 7–10, GIG of 4–7.
5. An outbound without a return in the fixture: "volta fora da janela".
6. "Até R$" and the highlights board use the total.
7. The choice survives a reload.
8. No horizontal scroll at 375 px.

Production: after the push, the next main-workflow deploy publishes `estadias`; check one
national and one European destination in the real panel.
