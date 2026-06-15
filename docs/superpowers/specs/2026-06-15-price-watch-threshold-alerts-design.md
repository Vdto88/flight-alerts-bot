# Price-Watch Threshold Alerts — Design Spec

**Date:** 2026-06-15
**Status:** Draft (pending user review)

---

## Overview

A second, independent alert signal on the same bot: alert when the cheapest fare from
**any airline** (GOL, LATAM, Azul, TAP, …) for a watched airport, within a specific month,
drops **to or below** a configured BRL limit. It complements the existing "Azul é a mais
barata" relative alert — that one fires when Azul beats the competition; this one fires when
a deal hits a price the user is hunting for, regardless of airline.

Key efficiency point: it reuses the Google Flights results the cycle already fetches per
route, so it adds **zero extra queries**. It also revives the dormant
`_format_money_alert` / "✈️ PASSAGEM BARATA DETECTADA" formatter in `telegram_bot.py`
(left over from the original threshold design, currently unused).

---

## Current State (baseline)

- `config.py`: `GROUPS` (region groups with `airports`, `windows`, `topic_id`), `month()`,
  `SearchWindow`, rolling window `WINDOW_MIN_DAYS=30`/`WINDOW_MAX_DAYS=120`.
- `routing.py`: `build_routes` (CNF↔airport, both directions, carries `topic_id`),
  `target_dates(airport, today, groups, win_min, win_max)` = rolling ∪ group windows.
- `alerts.py`: `evaluate(flights) -> list[AzulAlert]` (Azul-cheapest). **Unchanged by this work.**
- `cycle.py`: per route, searches dates, runs `evaluate`, sends via `send_azul_alert(..., topic_id)`.
- `telegram_bot.py`: `send_azul_alert(flight, comparison, topic_id=None)`. Also has the unused
  `format_alert` / `_format_money_alert` ("PASSAGEM BARATA DETECTADA") + `send_alert`.
- `cache.py`: `is_cached(flight)` / `save_to_cache(flight, ttl)` keyed on `flight.cache_key()`
  (`airline|origin|dest|date|price_floor`), 24h TTL.

---

## Requirements

### Functional
- A **price watch** is `(airport, window, max_price)`. Listed in `config.PRICE_WATCHES`.
- The watch's `airport` must belong to some `Group` — that gives it routes (both directions)
  and a Telegram topic. (A watch for an airport not in any group is a config error; see Testing.)
- For each departure date **inside a watch's window**, on **both directions** (CNF→airport and
  airport→CNF), if the **cheapest fare across all airlines** is **`<= max_price`**, emit a
  price alert for that cheapest flight.
- The watch's window is **added to the airport's searched dates** (rolling ∪ group windows ∪
  watch windows), so a month outside the rolling 30–120 window still gets searched.
- Price alerts post to the **destination's region topic** (the airport's group `topic_id`),
  with the same General-thread fallback as `send_azul_alert`.
- **Independent dedup** from the Azul alert: a separate cache namespace, same 24h TTL. A fare
  that is both Azul-cheapest and `<= max_price` may produce **both** alerts (rare overlap; both
  are informative). Within the price namespace, the same flight/price floor is not re-alerted
  for 24h.
- **No extra Google Flights queries:** the threshold check runs on the `flights` list already
  fetched per route in the cycle.

### Non-Functional
- Backwards compatible: empty `PRICE_WATCHES` → behaviour identical to today.
- Evaluation is pure and unit-testable, isolated from network/Telegram/cache I/O.

---

## Data Model — `config.py`

```python
@dataclass(frozen=True)
class PriceWatch:
    airport: str          # IATA; must be a member of some Group (for routing + topic)
    window: SearchWindow  # e.g. month(2026, 9)
    max_price: float      # BRL; alert when the cheapest fare (any airline) <= this


PRICE_WATCHES: list[PriceWatch] = [
    PriceWatch("SJK", month(2026, 9), 400.0),   # São José dos Campos, Sep/2026, <= R$400
]
```

`Group`, `SearchWindow`, `month()` are unchanged.

---

## Search Dates — `routing.py`

`target_dates` also unions in the windows of any `PriceWatch` for the airport, so the watch's
month is searched even when it falls outside the rolling window:

```python
def target_dates(airport, today, groups, win_min, win_max, watches=()):
    dates = {today + timedelta(days=n) for n in range(win_min, win_max + 1)}
    g = group_of(airport, groups)
    if g:
        for w in g.windows:
            dates.update(_window_dates(w.start, w.end))
    for pw in watches:                       # NEW
        if pw.airport == airport:
            dates.update(_window_dates(pw.window.start, pw.window.end))
    return sorted(d for d in dates if d >= today)
```

`watches` defaults to `()` so existing callers/tests are unaffected. `build_routes`, `group_of`,
`Route`, `_window_dates` are unchanged.

---

## Evaluation — `alerts.py`

```python
@dataclass
class ThresholdAlert:
    flight: Flight        # the cheapest fare on that date (any airline)
    max_price: float      # the watch limit it satisfied


def evaluate_threshold(flights: list[Flight], watches: list[PriceWatch]) -> list[ThresholdAlert]:
    """For one route's flights, return price alerts where the cheapest fare on a date that
    falls inside a watch's window is <= that watch's max_price. Airline-agnostic. Ignores
    fares with price <= 0. At most one alert per date (the tightest satisfied limit)."""
```

Logic: group flights by `departure_date`; for each date find the cheapest fare (min `price`,
`price > 0`); among the `watches` whose `window` covers that date and whose `max_price >=`
cheapest price, pick the one with the **smallest** `max_price` (tightest target the deal still
satisfies) and emit `ThresholdAlert(cheapest, that_max_price)`. `evaluate` (Azul) is untouched.

---

## Telegram — `telegram_bot.py`

```python
def format_price_alert(flight: Flight, max_price: float) -> str:
    # reuses the existing "✈️ PASSAGEM BARATA DETECTADA" body, adding a target line:
    #   🎯 abaixo do seu limite de R$ 400,00
    ...

async def send_price_alert(flight: Flight, max_price: float,
                           topic_id: int | None = None) -> bool:
    # mirrors send_azul_alert: post to message_thread_id=topic_id; on failure retry on the
    # General thread; return True only on a successful send.
```

The existing `_format_brl` / `_stops_label` helpers are reused. `send_azul_alert` and the
miles/legacy formatters are unchanged.

---

## Dedup — `cache.py`

Price alerts use a separate key namespace so they never collide with Azul alerts. Add an
optional `kind` argument threaded into the cache key:

```python
# airlines/base.py
def cache_key(self, kind: str = "") -> str:
    prefix = f"{kind}|" if kind else ""
    ...  # existing body, with `prefix` prepended

# cache.py
async def is_cached(flight, kind: str = "") -> bool: ...
async def save_to_cache(flight, ttl_hours: int = 24, kind: str = "") -> None: ...
```

Azul/legacy paths call with the default `kind=""` (unchanged keys). The cycle's price path
calls with `kind="price"`. SQLite schema is unchanged (the key string just carries the prefix).

---

## Cycle Flow — `cycle.py`

```
run_azul_cycle():
  for route in build_routes(GROUPS, AZUL_HUB):
      dates   = target_dates(route.non_hub, today, GROUPS, WIN_MIN, WIN_MAX, PRICE_WATCHES)
      flights = search_dates(route.origin, route.destination, dates, BATCH_SIZE)

      # existing Azul-cheapest signal (unchanged)
      for alert in evaluate(flights):
          if not is_cached(alert.flight):
              if send_azul_alert(alert.flight, alert.comparison, route.topic_id):
                  save_to_cache(alert.flight, CACHE_TTL_HOURS)

      # NEW price-watch signal — same flights, no extra queries
      watches = [w for w in PRICE_WATCHES if w.airport == route.non_hub]
      for pa in evaluate_threshold(flights, watches):
          if not is_cached(pa.flight, kind="price"):
              if send_price_alert(pa.flight, pa.max_price, route.topic_id):
                  save_to_cache(pa.flight, CACHE_TTL_HOURS, kind="price")
      ...
```

`cycle.py` imports `PRICE_WATCHES` and `evaluate_threshold`. Logging gains a price-alert count
in the per-route / final summary.

---

## Testing

New unit tests (pure, no network):
- `evaluate_threshold`: cheapest `<= limit` fires regardless of airline (e.g. a GOL fare);
  cheapest `> limit` does not; a date outside every watch window never fires; uses the **min**
  price across airlines; ignores `price <= 0`; tightest-limit selection when two watches overlap.
- `target_dates` with a `watches` arg: a watch window adds its dates (incl. a month outside the
  rolling window, e.g. Jan/2027); default `watches=()` keeps the old result; dedup with an
  overlapping group/rolling range.
- `cache` namespace: a flight saved with `kind="price"` is `is_cached(..., kind="price")` True
  but `is_cached(...)` (Azul) False, and vice versa.
- `cycle`: a sub-limit fare on a watched airport sends a price alert to the **group's topic_id**,
  caches under the price namespace, and dedups on the second pass; a fare that is both
  Azul-cheapest and sub-limit produces one Azul alert **and** one price alert.
- `send_price_alert`: passes `message_thread_id`, falls back to General on topic failure (mirror
  of the `send_azul_alert` tests); `format_price_alert` shows the route, price, airline and the
  `🎯 ... limite de R$ X` line.

Existing tests stay green (the new `watches` param defaults to `()`, `kind` defaults to `""`).

---

## File-by-file change summary

| File | Change |
|------|--------|
| `config.py` | Add `PriceWatch` dataclass + `PRICE_WATCHES` list (SJK Sep/2026 ≤ R$400). |
| `routing.py` | `target_dates(..., watches=())` unions price-watch windows for the airport. |
| `alerts.py` | Add `ThresholdAlert` + `evaluate_threshold(flights, watches)`. |
| `airlines/base.py` | `Flight.cache_key(kind="")` prefixes the key. |
| `cache.py` | `is_cached(flight, kind="")` / `save_to_cache(flight, ttl, kind="")`. |
| `telegram_bot.py` | `format_price_alert` + `send_price_alert(..., topic_id=None)` (General fallback). |
| `cycle.py` | Run `evaluate_threshold` on the same flights; send via `send_price_alert`; price-namespace dedup; pass `PRICE_WATCHES` to `target_dates`. |
| `tests/` | New tests above; existing tests unchanged. |

---

## Out of Scope (YAGNI)

- Round-trip pairing / total-trip pricing — still per one-way date, as today.
- Per-airline limits or "only GOL/LATAM" filtering — the trigger is the cheapest of any airline.
- Group-level or multi-airport watches — one airport per watch; add multiple `PriceWatch` rows
  for more. (Could be revisited later.)
- A dedicated "Ofertas" topic — alerts go to the destination's region topic (user's choice).
- Suppressing the Azul alert when a price alert fires — both are kept (user's choice).

**Comparison is inclusive: `<= max_price`** (a fare exactly at the limit alerts).
