# Azul Cheaper Alert — Design Spec

**Date:** 2026-06-13
**Status:** Approved (pending spec review)
**Supersedes:** parts of `2026-04-16-flight-alerts-bot-design.md` (cash/threshold/generic-alert path)

---

## Context — why this redesign

The original bot monitored GOL/LATAM/Azul via direct airline endpoints and alerted when any
fare dropped below a per-route absolute threshold. Verified live on 2026-06-13, every direct
path is dead:

- **GOL** (Smiles cash API) → HTTP 406, Akamai Bot Manager.
- **LATAM** (`/api/v1/flights`) → HTTP 404, `ApplicationNotFound` (endpoint removed) + Akamai.
- **Azul** (`voeazul.com.br`) → Akamai bot-challenge interstitial, no real content.
- **Smiles miles** (real Chrome via CDP) → captured nothing; cache empty.
- **Google Flights** via the `fast_flights` lib → **works**, returns GOL/LATAM/Azul cash fares.

The original absolute threshold (e.g. "R$350") was also the weak point of the product: hard to
pick, ages with inflation. This redesign drops the threshold model entirely and refocuses the
bot on a single, well-defined signal that is robust and useful for trip planning.

---

## Goal

A passive bot that, a few times per day, checks the Google Flights price for Azul vs. its
competitors on a fixed set of routes departing from CNF, and sends a Telegram alert **whenever
Azul is the cheapest airline on a given route + date**. No price threshold, no generic alerts.

Azul being the cheapest is rare (it is usually pricier), so any win is worth knowing — including
on long international routes where it will almost never happen.

---

## Requirements

### Functional
- For each configured route (CNF ↔ destination, both directions) and each target date, fetch all
  airlines' cheapest cash fare from Google Flights.
- **Alert when Azul's cheapest fare on a route+date is strictly lower than the cheapest
  competitor's fare on that same route+date.**
- The comparison ignores number of stops (Azul cheapest itinerary vs. competitor cheapest
  itinerary, regardless of connections). Stops are shown in the alert text.
- Require at least one non-Azul competitor for the date — if Google returns only Azul, no alert
  (the "cheaper than the others" claim would be vacuous).
- Target dates: a rolling window of **+30 to +90 days** by default, with optional per-destination
  date overrides (pin specific dates).
- De-duplicate: do not re-alert the same route + date + Azul price-floor within 24h. A genuine
  price drop (lower floor) re-alerts.
- Alerts go to a Telegram channel (broadcast). No interactive commands.

### Non-Functional
- One pass = fetch → evaluate → alert → persist dedup → exit. Scheduling is external (cron).
- Deployment-agnostic: identical `main.py` runs under GitHub Actions cron, Windows Task
  Scheduler, or any cron, with no code change.
- Errors/log to file + stdout only; no Telegram noise.
- No paid services. Free fallback is local Task Scheduler (known-good residential IP).

### Out of scope (this round)
- **Miles** (Smiles / Azul Fidelidade) — separate Akamai problem; files stay in repo, not run by
  this bot's main path. See `[[flight-scraper-akamai-state]]`.
- The generic "any airline below threshold" alert and the absolute threshold model — removed.

---

## Architecture

### Data source
`GoogleFlightsSearcher` (`airlines/google_flights.py`) becomes the **single** source. The
`fast_flights` library is queried once per (route, date); each result lists all airlines with
`name`, `price`, `stops`, `departure`, `arrival`. The direct scrapers `airlines/gol.py`,
`airlines/latam.py`, `airlines/azul.py` and their tests are **deleted**.

Because the bot now checks an arbitrary set of dates (a 30–90-day window or explicit overrides),
not a contiguous "next N days", add a `search_dates(origin, dest, dates: list[date],
batch_size=BATCH_SIZE)` method to `FlightSearcher` that fetches an explicit date list in
concurrent batches (same batching pattern as the existing `search_range`, but date-list driven).
The date list for each route is built in `cycle.py` from `AZUL_DATE_OVERRIDES` or the rolling
window. The old `search_range`/`days_ahead` path is no longer used by the main flow.

### Alert logic — new module `alerts.py`
A pure function, easy to unit-test in isolation:

```python
@dataclass
class AzulComparison:
    competitor: str          # e.g. "LATAM"
    competitor_price: float  # BRL
    savings: float           # competitor_price - azul_price

@dataclass
class AzulAlert:
    flight: Flight           # the cheapest Azul flight on that date
    comparison: AzulComparison

def evaluate(flights: list[Flight]) -> list[AzulAlert]:
    """Given all flights for one route across dates, return Azul-cheapest alerts."""
```

Logic, grouped by `departure_date`:
1. Drop flights with `price` None/≤ 0 (parse failures).
2. `azul = [f for f in date_flights if "azul" in f.airline.lower()]`
   `others = [f for f in date_flights if f not in azul]`
3. If `azul` empty or `others` empty → skip this date.
4. `azul_best = min(azul, key=price)`, `other_best = min(others, key=price)`.
5. If `azul_best.price < other_best.price` (strict) → emit
   `AzulAlert(azul_best, AzulComparison(other_best.airline, other_best.price,
   other_best.price - azul_best.price))`.

No stops filtering. Ties produce no alert.

### Cycle — `run_azul_cycle()` (in `cycle.py`, replacing `scheduler.py`)
```
for route in expanded AZUL_ROUTES:
    flights = google_searcher.search over the route's target dates
    for alert in alerts.evaluate(flights):
        if not cache.is_cached(alert.flight):
            telegram_bot.send_azul_alert(alert.flight, alert.comparison)
            cache.save_to_cache(alert.flight, CACHE_TTL_HOURS)
    log per-route summary
log cycle summary (routes, alerts, errors)
```
`AsyncIOScheduler`/`create_scheduler` is removed. The old `run_cycle` (generic/threshold) and
`run_miles_cycle` are removed from the main path.

### Entry point — `main.py` single pass
```
setup_logging()
await cache.init_db()
await run_azul_cycle()
# process exits
```
No `while True`, no APScheduler. Each cron tick is one full pass.

---

## Configuration (`config.py`)

```python
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID", "")

AZUL_HUB = "CNF"
AZUL_DESTINATIONS = [
    "GIG", "SDU", "CGH", "SSA", "SLZ", "IGU", "FLN", "NVT",   # domestic
    "FTE", "PNT", "PMC", "PUQ", "SCL", "BRC",                  # Patagonia / Chile / Argentina
]
# Default rolling window of departure dates to check, in days from today.
WINDOW_MIN_DAYS = 30
WINDOW_MAX_DAYS = 90
# Optional: pin explicit ISO dates for a destination instead of the rolling window.
AZUL_DATE_OVERRIDES: dict[str, list[str]] = {}   # e.g. {"SCL": ["2026-12-15", "2026-12-16"]}

CACHE_TTL_HOURS = 24
REQUEST_TIMEOUT = 15.0
BATCH_SIZE = 7   # concurrent Google Flights queries per batch
```

Route expansion (at load): for each `dest` in `AZUL_DESTINATIONS`, produce both
`AZUL_HUB → dest` and `dest → AZUL_HUB`. Target dates per route = the explicit override list if
present for that destination, else every day in `[today+WINDOW_MIN_DAYS, today+WINDOW_MAX_DAYS]`.

### Routes (14 destinations × 2 directions = 28 routes)

| Destination | IATA | Notes |
|---|---|---|
| Rio – Galeão | GIG | |
| Rio – Santos Dumont | SDU | |
| São Paulo – Congonhas | CGH | |
| Salvador | SSA | |
| São Luís (MA) | SLZ | |
| Foz do Iguaçu | IGU | |
| Florianópolis | FLN | |
| Balneário Camboriú | NVT | Navegantes airport serves Balneário |
| El Calafate | FTE | also covers El Chaltén (no airport there) |
| Puerto Natales | PNT | |
| Puerto Montt | PMC | |
| Punta Arenas | PUQ | |
| Santiago | SCL | |
| Bariloche | BRC | |

---

## Cache / dedup

Unchanged from today (`cache.py`, SQLite at `data/cache.db`). The dedup key is
`Flight.cache_key()` = `AZUL|origin|dest|date|price_floor` where
`price_floor = floor(price / 10) * 10`. Because only Azul flights are ever alerted now, no
alert-type discriminator is needed. Expired entries (>24h) purged at the start of each cycle.

Persistence across runs:
- **Local** (Task Scheduler): `data/cache.db` persists on disk naturally.
- **GitHub Actions**: ephemeral runner → wrap the job with `actions/cache` keyed on a stable key
  so `data/cache.db` is restored at start and saved at end. A tiny file accessed several times a
  day stays well inside cache retention.

---

## Telegram alert format

New formatter `format_azul_alert(flight, comparison)` + `send_azul_alert(...)` in
`telegram_bot.py`. Existing money/miles formatters stay (used by the dormant miles path).

```
🔵 AZUL É A MAIS BARATA

🛫 CNF → SSA
💰 R$ 300,00  (Azul)
📊 vs R$ 396,00 (LATAM) — economia de R$ 96,00
📅 15/07/2026 • 12h00 → 13h15
🏢 Azul • Direto            (or "1 parada" / "2 paradas")
🔗 [Reservar agora](link Google Flights)

⏰ Detectado às 14:32
```

`MARKDOWN` parse mode, link preview disabled (as today). Booking link points to the Google
Flights search for that route+date (consistent with the existing fallback URL builder).

---

## Deployment

### Primary — GitHub Actions (free, serverless)
`.github/workflows/azul-alert.yml`:
- `on.schedule`: cron 3×/day (UTC; e.g. `0 11,17,23 * * *` ≈ 08/14/20 BRT). Best-effort timing
  is fine for a planning-horizon product.
- Job: checkout → setup Python 3.11 → `pip install -r requirements.txt` → restore `data/`
  via `actions/cache` → `python main.py` → save cache.
- Secrets: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHANNEL_ID` as repo secrets → env.
- Estimated cost: ~10 min/run × 3/day × 30 ≈ 900 min/month, inside the 2000-min private-repo
  free tier.

### Free fallback — local Windows Task Scheduler
The same `python main.py`, scheduled 3×/day. Uses the residential IP that is verified to work
with Google Flights. Requires the machine to be on at run time. Zero code change vs. Actions.

### Validation step (first real run)
Confirm Google Flights actually responds from the GitHub runner IP. If it is blocked/rate-limited
at the 28-route volume, fall back to local Task Scheduler. No code change either way.

---

## Testing (TDD)

New `tests/test_alerts.py` covers `evaluate()`:
- Azul strictly cheapest vs. one competitor → one alert, correct savings/competitor.
- Azul cheapest but tie with competitor → no alert.
- Azul present but a competitor is cheaper → no alert.
- Azul is the only airline that date → no alert.
- Multiple dates → independent per-date decisions.
- Flights with missing/zero price are ignored.
- Stops are not filtered (a 2-stop Azul still wins if cheaper).

Adjust `tests/test_google_flights.py` as needed (cover `search_dates`). Update/replace
`tests/test_scheduler.py` for `run_azul_cycle`. Delete `tests/test_gol.py`,
`tests/test_latam.py`, `tests/test_azul.py`. Keep `tests/test_cache.py`,
`tests/test_telegram_bot.py` (add a case for the Azul format). Leave the miles tests
`tests/test_smiles_miles.py` and `tests/test_azul_miles.py` untouched (dormant code).

---

## Files

**Add:** `alerts.py`, `cycle.py`, `tests/test_alerts.py`, `.github/workflows/azul-alert.yml`.
**Edit:** `config.py`, `main.py`, `telegram_bot.py`, `requirements.txt` (drop APScheduler if
unused elsewhere), `tests/test_scheduler.py` → cycle tests.
**Delete:** `airlines/gol.py`, `airlines/latam.py`, `airlines/azul.py`, `scheduler.py`,
`tests/test_gol.py`, `tests/test_latam.py`, `tests/test_azul.py`.
**Untouched (dormant, out of scope):** `airlines/smiles_miles.py`, `airlines/azul_miles.py`,
`scripts/harvest_cookies.py`.
