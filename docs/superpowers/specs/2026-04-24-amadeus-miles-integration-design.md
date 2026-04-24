# Design: Amadeus + Miles Integration

**Date:** 2026-04-24
**Status:** Approved

## Problem

The existing per-airline HTTP scrapers (GOL/Smiles, LATAM, AZUL) are failing due to 403/CloudFlare blocks. Additionally, the system has no miles price monitoring. This design replaces the broken cash scrapers with the Amadeus API and adds miles searchers for all three Brazilian loyalty programs.

## Goals

1. Stable cash price monitoring via Amadeus (replaces GOL/LATAM/AZUL scrapers)
2. Miles price monitoring: Smiles (GOL), LATAM Pass, TudoAzul (AZUL)
3. Telegram alerts for both cash drops and miles drops
4. All departures from CNF (Confins) for miles routes

## Non-Goals

- Displaying both cash and miles prices in the same alert
- Miles-to-cash conversion or comparison
- Award availability (seats count)

---

## Architecture

```
config.py
  ROUTES          → cash routes with per-airline thresholds (existing + new CNF routes)
  MILES_ROUTES    → miles routes with per-program thresholds (new)

airlines/
  base.py         → Flight extended with currency + miles_program fields
  amadeus.py      → replaces gol.py / latam.py / azul.py for cash prices
  smiles.py       → Smiles miles searcher (new)
  latam_miles.py  → LATAM Pass miles searcher (new)
  azul_miles.py   → TudoAzul miles searcher (new)
  google_flights.py → kept as Amadeus fallback

scheduler.py      → cash cycle (Amadeus) + miles cycle (3 programs), run in parallel
telegram_bot.py   → format_alert extended for miles currency
cache.py          → cache_key includes currency|miles_program (no change to interface)

Deleted: gol.py, latam.py, azul.py
```

---

## Data Model

### `Flight` (base.py)

Two new optional fields added to the existing dataclass:

```python
currency: str = "BRL"      # "BRL" or "MILHAS"
miles_program: str = ""    # "SMILES" | "LATAM_PASS" | "TUDOAZUL"
```

- `price` holds BRL amount when `currency="BRL"`, miles count when `currency="MILHAS"`
- `cache_key()` updated to include `currency|miles_program` to prevent cross-type collisions

---

## Config

### ROUTES (cash) — updated

```python
ROUTES = [
    {"from": "CNF", "to": "GRU", "threshold": 350,  "airlines": ["GOL", "LATAM", "AZUL"]},
    {"from": "CNF", "to": "CGH", "threshold": 350,  "airlines": ["GOL", "LATAM", "AZUL"]},
    {"from": "CNF", "to": "GIG", "threshold": 400,  "airlines": ["GOL", "LATAM", "AZUL"]},
    {"from": "CNF", "to": "SDU", "threshold": 400,  "airlines": ["GOL", "LATAM", "AZUL"]},
    {"from": "CNF", "to": "POA", "threshold": 500,  "airlines": ["GOL", "LATAM", "AZUL"]},
    {"from": "CNF", "to": "IGU", "threshold": 500,  "airlines": ["GOL", "LATAM", "AZUL"]},
    {"from": "CNF", "to": "SLZ", "threshold": 600,  "airlines": ["GOL", "LATAM", "AZUL"]},
    {"from": "GRU", "to": "LIS", "threshold": 2000, "airlines": ["LATAM", "GOL"]},
    {"from": "GRU", "to": "MIA", "threshold": 1500, "airlines": ["LATAM", "GOL"]},
]
```

### MILES_ROUTES (new)

```python
MILES_ROUTES = [
    {"from": "CNF", "to": "GRU", "thresholds": {"SMILES": 10000, "LATAM_PASS": 10000, "TUDOAZUL": 14000}},
    {"from": "CNF", "to": "CGH", "thresholds": {"SMILES": 10000, "LATAM_PASS": 10000, "TUDOAZUL": 14000}},
    {"from": "CNF", "to": "GIG", "thresholds": {"SMILES": 10000, "LATAM_PASS": 10000, "TUDOAZUL": 14000}},
    {"from": "CNF", "to": "SDU", "thresholds": {"SMILES": 10000, "LATAM_PASS": 10000, "TUDOAZUL": 14000}},
    {"from": "CNF", "to": "POA", "thresholds": {"SMILES": 10000, "LATAM_PASS": 10000, "TUDOAZUL": 14000}},
    {"from": "CNF", "to": "IGU", "thresholds": {"SMILES": 10000, "LATAM_PASS": 10000, "TUDOAZUL": 14000}},
    {"from": "CNF", "to": "SLZ", "thresholds": {"SMILES": 10000, "LATAM_PASS": 10000, "TUDOAZUL": 14000}},
]
```

New env vars:
```
AMADEUS_API_KEY=...
AMADEUS_API_SECRET=...
```

---

## API Integrations

### Amadeus (cash)

- Registration: developers.amadeus.com (free)
- SDK: `amadeus-python` (add to requirements.txt)
- Airline IATA codes: GOL=`G3`, LATAM=`JJ`, AZUL=`AD`
- Single `AmadeusSearcher` class takes airline code as constructor param
- Fallback: `GoogleFlightsSearcher` if Amadeus returns empty

**Two-phase search to stay within API limits:**

The base `search_range` makes 1 call per date (60 calls per route). For Amadeus that would be ~1,620 calls/cycle — far over the free tier. `AmadeusSearcher` overrides `search_range` with a two-phase approach:

1. **Phase 1** — `GET /v1/shopping/flight-dates`: one call per route returns cheapest price per date for the full range (up to 330 days ahead). Filters dates below threshold.
2. **Phase 2** — `GET /v2/shopping/flight-offers`: called only for dates identified in phase 1 as below threshold, to get airline, times, and booking URL.

This results in ~1 call/route for phase 1 + a small number of phase 2 calls only when cheap fares are found. Typical cycle: 9 routes × 1 = 9 calls + occasional phase 2 calls.

### Smiles (miles — GOL)

- URL: `https://api-air-flightsearch-prd.smiles.com.br/v1/airlines/search`
- Same URL as broken cash scraper, but with `currencyCode=SMILES`
- Price field: `totalSmiles` in response payload
- Booking URL: smiles.com.br resgate path

### LATAM Pass (miles — LATAM)

- URL: same as broken LATAM cash scraper
- Param change: `redemption=true`
- Price field: points amount in response
- Booking URL: latamairlines.com with redemption flag

### TudoAzul (miles — AZUL)

- URL: `https://api.voeazul.com.br/tudo-azul/v1/flights/search` (app's internal API)
- Auth: `Authorization: Basic` with public app credential (no user login needed)
- Returns points in JSON directly — no HTML scraping
- Booking URL: tudoazul.com.br resgate path

---

## Scheduler

`run_cycle()` runs two sub-cycles in parallel:

**Cash cycle:**
```
for route in ROUTES:
    for airline in route["airlines"]:
        AmadeusSearcher(airline).search_range(origin, dest)
        → fallback GoogleFlightsSearcher if empty
        → filter price < threshold
        → cache check → send_alert
```

**Miles cycle:**
```
for route in MILES_ROUTES:
    SmilesSearcher, LatamMilesSearcher, AzulMilesSearcher run in parallel
    → each filters points < threshold[program]
    → cache check → send_alert
```

Both cycles run every 45 minutes. Estimated Amadeus API calls: 9 routes × 1 (phase 1) + occasional phase 2 calls = well within free tier (2,000 calls/month).

---

## Telegram Alert Format

`format_alert` in `telegram_bot.py` branches on `flight.currency`:

**Cash alert (existing format):**
```
✈️ PASSAGEM BARATA DETECTADA

🛫 CNF → GRU
💰 R$ 289,00
📅 15/05/2026 • 07h40 → 09h10
🏢 GOL • Direto
🔗 Reservar agora

⏰ Detectado às 14:32
```

**Miles alert (new format):**
```
🎯 MILHAS BARATAS DETECTADAS

🛫 CNF → GRU
🏆 8.500 pontos Smiles
📅 15/05/2026 • 07h40 → 09h10
🏢 GOL • Direto
🔗 Resgatar agora

⏰ Detectado às 14:32
```

---

## Error Handling

- Any searcher returning `[]` is silent — no crash, no alert
- Amadeus auth failure logs an error and falls back to GoogleFlights
- Miles API failure per-program is independent — other programs continue normally
- Cache key collision between cash and miles is prevented by `currency|miles_program` suffix

---

## Files Changed

| Action | File |
|--------|------|
| Modify | `airlines/base.py` |
| Modify | `config.py` |
| Modify | `scheduler.py` |
| Modify | `telegram_bot.py` |
| Modify | `.env.example` |
| Modify | `requirements.txt` |
| New | `airlines/amadeus.py` |
| New | `airlines/smiles.py` |
| New | `airlines/latam_miles.py` |
| New | `airlines/azul_miles.py` |
| Delete | `airlines/gol.py` |
| Delete | `airlines/latam.py` |
| Delete | `airlines/azul.py` |
