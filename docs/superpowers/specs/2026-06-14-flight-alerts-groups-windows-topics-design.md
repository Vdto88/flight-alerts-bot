# Flight Alerts — Region Groups, Search Windows & Telegram Topics — Design Spec

**Date:** 2026-06-14
**Status:** Draft (pending user review)

---

## Overview

Three additions to the existing "Azul é a mais barata" alert bot, all on the same
codebase and same single-pass / GitHub Actions cron model:

1. **Region groups** — replace the flat `AZUL_DESTINATIONS` list with named groups
   ("Patagônia", "Foz do Iguaçu", "Portugal"...). A group is a collection of airports
   that shares an optional search window and an optional Telegram topic.
2. **Specific search windows** — per group, search one or more explicit month/date
   ranges (e.g. "outubro/2026" for Foz, "fevereiro/2027" for Patagônia) **in addition**
   to the existing rolling 30–90 day window. The rolling window stays on for every
   airport, so out-of-window deals still surface.
3. **Telegram topics (Forum mode)** — each group maps to a topic (sub-thread) inside a
   Forum-enabled supergroup. Alerts post to the topic of their destination's group.
   Until topics are configured, everything still posts to a single chat exactly as today.

These are independent features bundled into one spec because they share one unifying
concept — the **group** — and touch the same three files (`config.py`, `cycle.py`,
`telegram_bot.py`).

---

## Current State (baseline)

- `config.py`: `AZUL_HUB = "CNF"`, flat `AZUL_DESTINATIONS` list, `WINDOW_MIN_DAYS=30`,
  `WINDOW_MAX_DAYS=90`, and a raw `AZUL_DATE_OVERRIDES: dict[str, list[str]]` hook.
- `cycle.py`: `build_routes()` (CNF ↔ each dest, both directions), `target_dates(non_hub, today)`
  (override dates or rolling window), `run_azul_cycle()` orchestrator.
- `telegram_bot.py`: `send_azul_alert(flight, comparison) -> bool` → single chat
  (`TELEGRAM_CHANNEL_ID`), returns False on failure so the caller only caches on success.
- `alerts.py`: `evaluate()` returns `AzulAlert` when the cheapest Azul fare beats the
  cheapest competitor on a date. **Unchanged by this work.**
- Cache (`cache.py`), `main.py`, `airlines/*`: **unchanged.**

The raw `AZUL_DATE_OVERRIDES` hook is superseded by groups + windows and will be removed.

---

## Requirements

### Functional

- Destinations are organized into named **groups** (regions). A group has: a name, a list
  of airport IATA codes, zero or more search windows, and an optional Telegram topic id.
- Every airport is always searched on the **rolling window** (today+30 … today+90).
- A group's **windows are additive**: their dates are searched on top of the rolling window.
- A window is an explicit date range. A `month(year, month)` helper expands to the whole
  calendar month. Dates in the past are dropped; if a window is entirely past, it yields nothing.
- Routes are CNF ↔ each airport in both directions (unchanged shape).
- An alert posts to the Telegram **topic** of its destination's group. If the group has no
  topic id (or the send to that topic fails), it falls back to the chat's General thread.
- Dedup behaviour (24h, price-floor cache key) is unchanged and topic-independent.
- No interactive bot commands — passive monitoring only (unchanged).

### Non-Functional

- Backwards compatible: with all `topic_id = None` and the chat unchanged, behaviour is
  identical to today (single destination). No Telegram setup required to keep running.
- Routing/date logic is pure and unit-testable, isolated from I/O.
- The added far-future windows must not blow the GitHub Actions job timeout (see Performance).

---

## Data Model

New, in `config.py`:

```python
from dataclasses import dataclass, field
from datetime import date

@dataclass(frozen=True)
class SearchWindow:
    start: date          # inclusive, e.g. date(2027, 2, 1)
    end: date            # inclusive, e.g. date(2027, 2, 28)

def month(year: int, m: int) -> SearchWindow:
    """Whole calendar month as a window. month(2027, 2) -> Feb 1..Feb 28/29, 2027."""
    import calendar
    last = calendar.monthrange(year, m)[1]
    return SearchWindow(date(year, m, 1), date(year, m, last))

@dataclass(frozen=True)
class Group:
    name: str                       # display name; also the Telegram topic name
    airports: tuple[str, ...]       # IATA codes, e.g. ("FTE", "PNT", ...)
    windows: tuple[SearchWindow, ...] = ()   # extra ranges; empty = rolling-only
    topic_id: int | None = None     # Telegram forum topic id; None = General thread
```

`Flight`, `AzulComparison`, `AzulAlert` are unchanged.

---

## Configuration (final)

```python
AZUL_HUB = "CNF"

GROUPS: list[Group] = [
    Group("Rio de Janeiro", ("GIG", "SDU")),
    Group("São Paulo",      ("CGH",)),
    Group("São Luís",       ("SLZ",)),
    Group("Sul",            ("FLN", "NVT")),
    Group("Foz do Iguaçu",  ("IGU",),  (month(2026, 10),)),
    Group("Patagônia",      ("FTE", "PNT", "PMC", "PUQ", "BRC", "SCL"),
                            (month(2027, 2),)),
    # --- Europa ---
    Group("Portugal",       ("LIS", "OPO")),
    Group("Espanha",        ("MAD", "BCN")),
    Group("Itália",         ("FCO", "MXP")),
    Group("França",         ("CDG", "ORY")),
]

WINDOW_MIN_DAYS = 30
WINDOW_MAX_DAYS = 90
BATCH_SIZE = 7
CACHE_TTL_HOURS = 24
```

**Changes from baseline:** `SSA` removed (was in the Nordeste group). 8 European airports
added across 4 country groups. `AZUL_DESTINATIONS` and `AZUL_DATE_OVERRIDES` removed.

**Totals:** 21 airports × 2 directions = **42 routes**. Two groups carry windows
(Foz → Oct 2026, Patagônia → Feb 2027). Europe is rolling-window only for now (a window
can be added later with one `month(...)` entry).

---

## Routing & Dates — `routing.py` (new module)

Pure functions extracted out of `cycle.py` so they can be unit-tested without network/I/O.

```python
@dataclass(frozen=True)
class Route:
    origin: str
    destination: str
    non_hub: str            # the non-CNF endpoint (carries the window/topic)
    topic_id: int | None

def build_routes(groups, hub) -> list[Route]:
    """CNF ↔ each airport of each group, both directions. topic_id from the group."""

def target_dates(airport, today, groups,
                 win_min, win_max) -> list[date]:
    """Rolling window (today+win_min .. today+win_max) UNION the dates of every
    SearchWindow of the airport's group. Deduplicated, sorted, past dates dropped."""
```

`group_of(airport, groups) -> Group` is the shared lookup used by both.

### Window expansion semantics

- A `SearchWindow(start, end)` expands to every date `start..end` inclusive.
- Union with the rolling window, then drop any date `< today`, dedup, sort ascending.
- If a window is entirely in the past it contributes nothing (harmless — e.g. after Oct 2026
  passes, the Foz window goes quiet until the config is updated).
- **Google Flights only has fares ~11 months out.** Dates beyond that simply return no
  flights — no special handling needed; Feb 2027 is within range as of mid-2026.

---

## Cycle Flow — `cycle.py`

```
run_azul_cycle():
  purge expired cache
  for route in build_routes(GROUPS, AZUL_HUB):
      dates = target_dates(route.non_hub, today, GROUPS, WINDOW_MIN_DAYS, WINDOW_MAX_DAYS)
      flights = searcher.search_dates(route.origin, route.destination, dates, BATCH_SIZE)
      for alert in evaluate(flights):
          if not cached(alert.flight):
              sent = telegram_bot.send_azul_alert(alert.flight, alert.comparison, route.topic_id)
              if sent: cache(alert.flight)
      log per-route summary
  log cycle summary (alerts, errors)
```

Only difference vs today: routes come from groups, dates include group windows, and the
group's `topic_id` is threaded through to the send call.

---

## Telegram Topics — `telegram_bot.py`

```python
async def send_azul_alert(flight, comparison, topic_id: int | None = None) -> bool:
    message = format_azul_alert(flight, comparison)   # unchanged formatter
    bot = get_bot()
    try:
        await bot.send_message(chat_id=TELEGRAM_CHANNEL_ID, text=message,
                               parse_mode=MARKDOWN, link_preview_options=...,
                               message_thread_id=topic_id)   # None → General thread
        return True
    except Exception:
        if topic_id is not None:
            # topic may have been deleted / chat isn't a forum → retry on General
            try:
                await bot.send_message(chat_id=TELEGRAM_CHANNEL_ID, text=message, ...)  # no thread id
                return True
            except Exception as e:
                logger.error(...); return False
        logger.error(...); return False
```

`topic_id=None` keeps the current default param, so existing call sites and tests still work.

### One-time Telegram setup (done by the user, guided)

1. The alert destination must be a **Forum-enabled supergroup** (Telegram → group settings →
   *Topics* ON). Topics do **not** exist in channels, so a channel-only `TELEGRAM_CHANNEL_ID`
   must move to a forum supergroup id (the `-100…` form).
2. Add the bot to that supergroup as **admin**.
3. Create the topics (one per group you want separated: Foz, Patagônia, Portugal, ...).
4. Run `scripts/list_topics.py` (new): send one message in each topic, the script reads
   `getUpdates` and prints `topic name → message_thread_id`. Paste the ids into `GROUPS`.

Until step 4 is done, all `topic_id` stay `None` and every alert lands in the General
thread — i.e. the bot keeps working with zero Telegram changes.

---

## Performance / Cost

- Rolling window = 61 dates × 42 routes = ~2 562 base queries/pass.
- Windows add: Foz (1 airport × 2 dir × 31) + Patagônia (6 × 2 × 28) ≈ 398 queries.
- ≈ **2 960 Google Flights queries/pass**, batched 7-concurrent (`search_dates`).
- Mitigation: raise the GitHub Actions `timeout-minutes` (currently 30) to **60** with margin.
  If runtime is still a problem, future options (out of scope now): lower window density
  (e.g. weekends only), or cap windowed airports. Not blocking.

---

## Testing

New unit tests (pure, no network) in `tests/`:

- `month()` expansion (incl. Feb leap-year boundary) and `SearchWindow` date enumeration.
- `target_dates`: rolling-only airport; rolling ∪ window; dedup of overlapping dates;
  past-date dropping; fully-past window → rolling only.
- `build_routes`: both directions, correct `topic_id` and `non_hub` per airport;
  `group_of` lookup.
- `send_azul_alert`: passes `message_thread_id` when topic set; retries on General when the
  topic send raises; returns False only when both attempts fail. (Bot mocked.)

Existing tests keep passing; any that reference `AZUL_DESTINATIONS`/`AZUL_DATE_OVERRIDES`
are updated to the group model.

---

## File-by-file change summary

| File | Change |
|------|--------|
| `config.py` | Add `SearchWindow`, `Group`, `month()`, `GROUPS`. Remove `AZUL_DESTINATIONS`, `AZUL_DATE_OVERRIDES`. |
| `routing.py` (new) | `Route`, `build_routes`, `target_dates`, `group_of` (pure). |
| `cycle.py` | Use `routing.build_routes`/`target_dates`; thread `topic_id` to send. |
| `telegram_bot.py` | `send_azul_alert(..., topic_id=None)` + General-thread fallback. |
| `scripts/list_topics.py` (new) | One-off helper to print `topic name → thread id`. |
| `.github/workflows/azul-alert.yml` | `timeout-minutes: 60`. |
| `tests/` | New tests above; update any referencing removed config. |

---

## Out of Scope (YAGNI)

- Recurring/auto-rolling windows (e.g. "always next February"). Windows are explicit
  year-months; update the config each year.
- Per-airport (vs per-group) windows or topics — groups cover the stated need.
- Round-trip pairing / price aggregation across legs — still per one-way date, as today.
- Interactive bot commands, per-topic thresholds, miles topics.
```