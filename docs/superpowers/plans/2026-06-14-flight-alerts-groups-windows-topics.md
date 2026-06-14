# Region Groups, Search Windows & Telegram Topics — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Organize flight-alert destinations into named region groups, let each group search extra month windows on top of the rolling window, and route each alert to its group's Telegram forum topic.

**Architecture:** Replace the flat `AZUL_DESTINATIONS` list with a declarative `GROUPS` list (`config.py`). A new pure `routing.py` derives routes and per-airport search dates (rolling window ∪ group windows) and carries each group's `topic_id`. `cycle.py` becomes a thin orchestrator. `telegram_bot.send_azul_alert` gains a `topic_id` param and posts via `message_thread_id`, falling back to the General thread on failure. Backwards compatible: with all `topic_id=None` the bot behaves exactly as today.

**Tech Stack:** Python 3.11, `python-telegram-bot==21.3.0`, `fast-flights`, `aiosqlite`, `pytest`/`pytest-asyncio` (`asyncio_mode=auto`).

**Working dir:** All paths are relative to `C:\FlightAlert` (branch `feature/groups-windows-topics`). Run tests with `python -m pytest` from that root.

**Commits:** Every commit message must end with the trailer line:
`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`

---

## File Structure

| File | Responsibility | Action |
|------|----------------|--------|
| `config.py` | Declarative data: env, `SearchWindow`, `month()`, `Group`, `GROUPS`, window/batch constants. No logic. | Modify (add model + GROUPS; later remove old constants) |
| `routing.py` | Pure functions: `Route`, `group_of`, `build_routes`, `target_dates`. No I/O. | Create |
| `cycle.py` | Orchestrator: iterate routes, search, evaluate, send, cache, log. | Modify |
| `telegram_bot.py` | Format + send alerts; topic routing + General fallback. | Modify |
| `scripts/list_topics.py` | One-off helper to discover forum topic ids. | Create |
| `.github/workflows/azul-alert.yml` | Cron job; raise timeout for the extra window queries. | Modify |
| `tests/test_config_groups.py` | Unit tests for the config model. | Create |
| `tests/test_routing.py` | Unit tests for routing/date logic. | Create |
| `tests/test_cycle.py` | Cycle behaviour (move route/date tests out to routing). | Modify |
| `tests/test_telegram_bot.py` | Add topic-routing + fallback tests. | Modify |

**Ordering rationale:** config additions are *additive* (old constants kept) so the suite stays green; `telegram_bot` changes before `cycle` so the new `topic_id` arg exists when `cycle` calls it; old config constants are removed only after `cycle` and its tests stop referencing them.

---

### Task 1: Config model — `SearchWindow`, `month()`, `Group`, `GROUPS`

**Files:**
- Modify: `config.py` (add imports + model + `GROUPS`; keep `AZUL_DESTINATIONS`/`AZUL_DATE_OVERRIDES` for now)
- Test: `tests/test_config_groups.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_config_groups.py`:

```python
from datetime import date
import config


def test_month_expands_to_full_calendar_month():
    w = config.month(2027, 2)
    assert w.start == date(2027, 2, 1)
    assert w.end == date(2027, 2, 28)


def test_month_handles_leap_year():
    assert config.month(2024, 2).end == date(2024, 2, 29)


def test_groups_have_no_ssa():
    airports = [a for g in config.GROUPS for a in g.airports]
    assert "SSA" not in airports


def test_total_airports_unique_count():
    airports = [a for g in config.GROUPS for a in g.airports]
    assert len(airports) == 21
    assert len(set(airports)) == 21


def test_groups_include_europe_with_two_airports_each():
    by_name = {g.name: g for g in config.GROUPS}
    assert by_name["Portugal"].airports == ("LIS", "OPO")
    assert by_name["Espanha"].airports == ("MAD", "BCN")
    assert by_name["Itália"].airports == ("FCO", "MXP")
    assert by_name["França"].airports == ("CDG", "ORY")


def test_foz_and_patagonia_carry_windows():
    by_name = {g.name: g for g in config.GROUPS}
    assert by_name["Foz do Iguaçu"].windows == (config.month(2026, 10),)
    assert by_name["Patagônia"].windows == (config.month(2027, 2),)


def test_groups_default_to_no_topic():
    assert all(g.topic_id is None for g in config.GROUPS)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config_groups.py -v`
Expected: FAIL — `AttributeError: module 'config' has no attribute 'month'` (and `GROUPS`).

- [ ] **Step 3: Write minimal implementation**

In `config.py`, add these imports at the top (after the existing `import os` / `from dotenv import load_dotenv`):

```python
import calendar
from dataclasses import dataclass
from datetime import date
```

Then add the model and `GROUPS` immediately after the `AZUL_HUB` line (leave `AZUL_DESTINATIONS` and `AZUL_DATE_OVERRIDES` in place for now):

```python
@dataclass(frozen=True)
class SearchWindow:
    start: date          # inclusive
    end: date            # inclusive


def month(year: int, m: int) -> "SearchWindow":
    """Whole calendar month as a window. month(2027, 2) -> Feb 1..Feb 28/29."""
    last = calendar.monthrange(year, m)[1]
    return SearchWindow(date(year, m, 1), date(year, m, last))


@dataclass(frozen=True)
class Group:
    name: str                                  # display name; also the topic name
    airports: tuple[str, ...]                  # IATA codes
    windows: tuple[SearchWindow, ...] = ()     # extra ranges; empty = rolling-only
    topic_id: int | None = None                # Telegram forum topic id; None = General


GROUPS: list[Group] = [
    Group("Rio de Janeiro", ("GIG", "SDU")),
    Group("São Paulo",      ("CGH",)),
    Group("São Luís",       ("SLZ",)),
    Group("Sul",            ("FLN", "NVT")),
    Group("Foz do Iguaçu",  ("IGU",), (month(2026, 10),)),
    Group("Patagônia",      ("FTE", "PNT", "PMC", "PUQ", "BRC", "SCL"), (month(2027, 2),)),
    # --- Europa ---
    Group("Portugal",       ("LIS", "OPO")),
    Group("Espanha",        ("MAD", "BCN")),
    Group("Itália",         ("FCO", "MXP")),
    Group("França",         ("CDG", "ORY")),
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_config_groups.py -v`
Expected: PASS (7 passed).

- [ ] **Step 5: Confirm nothing else broke**

Run: `python -m pytest -q`
Expected: all existing tests still PASS (old `test_cycle.py` route/date tests still reference `AZUL_DESTINATIONS`, which still exists — green).

- [ ] **Step 6: Commit**

```bash
git add config.py tests/test_config_groups.py
git commit -m "feat(config): add SearchWindow/Group model and GROUPS"
```

---

### Task 2: `routing.py` — `Route`, `group_of`, `build_routes`

**Files:**
- Create: `routing.py`
- Test: `tests/test_routing.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_routing.py`:

```python
import config
import routing


def test_build_routes_both_directions_and_count():
    routes = routing.build_routes(config.GROUPS, config.AZUL_HUB)
    assert len(routes) == 42  # 21 airports x 2 directions
    pairs = {(r.origin, r.destination) for r in routes}
    assert ("CNF", "GIG") in pairs
    assert ("GIG", "CNF") in pairs
    assert all("CNF" in (r.origin, r.destination) for r in routes)


def test_build_routes_carries_non_hub_and_topic():
    routes = routing.build_routes(config.GROUPS, config.AZUL_HUB)
    igu = [r for r in routes if r.non_hub == "IGU"]
    assert len(igu) == 2
    assert all(r.topic_id is None for r in igu)  # Foz has no topic configured yet


def test_group_of_finds_group():
    g = routing.group_of("FTE", config.GROUPS)
    assert g is not None and g.name == "Patagônia"


def test_group_of_returns_none_for_unknown():
    assert routing.group_of("XXX", config.GROUPS) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_routing.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'routing'`.

- [ ] **Step 3: Write minimal implementation**

Create `routing.py`:

```python
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from config import Group


@dataclass(frozen=True)
class Route:
    origin: str
    destination: str
    non_hub: str            # the non-hub endpoint (carries window + topic)
    topic_id: Optional[int]


def group_of(airport: str, groups: list[Group]) -> Optional[Group]:
    for g in groups:
        if airport in g.airports:
            return g
    return None


def build_routes(groups: list[Group], hub: str) -> list[Route]:
    """hub <-> each airport of each group, both directions."""
    routes: list[Route] = []
    for g in groups:
        for airport in g.airports:
            routes.append(Route(hub, airport, airport, g.topic_id))
            routes.append(Route(airport, hub, airport, g.topic_id))
    return routes
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_routing.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add routing.py tests/test_routing.py
git commit -m "feat(routing): Route + group_of + build_routes"
```

---

### Task 3: `routing.target_dates` — rolling window ∪ group windows

**Files:**
- Modify: `routing.py` (add `_window_dates` + `target_dates`)
- Test: `tests/test_routing.py` (add cases)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_routing.py`:

```python
from datetime import date, timedelta


def test_target_dates_rolling_only():
    today = date(2026, 1, 1)
    dates = routing.target_dates("GIG", today, config.GROUPS, 30, 90)
    assert dates[0] == today + timedelta(days=30)
    assert dates[-1] == today + timedelta(days=90)
    assert len(dates) == 61


def test_target_dates_includes_group_window():
    today = date(2026, 6, 1)
    dates = routing.target_dates("IGU", today, config.GROUPS, 30, 90)
    assert date(2026, 10, 1) in dates
    assert date(2026, 10, 31) in dates
    assert any(d > today + timedelta(days=90) for d in dates)  # beyond rolling end


def test_target_dates_dedups_overlapping_window():
    today = date(2026, 1, 1)
    custom = [config.Group("T", ("ZZZ",),
                           (config.SearchWindow(date(2026, 2, 1), date(2026, 2, 5)),))]
    dates = routing.target_dates("ZZZ", today, custom, 30, 90)
    assert dates == sorted(dates)
    assert len(dates) == len(set(dates))
    assert len(dates) == 61  # Feb 1-5 already inside the Jan31..Apr1 rolling range


def test_target_dates_drops_fully_past_window():
    today = date(2026, 1, 1)
    custom = [config.Group("T", ("ZZZ",),
                           (config.SearchWindow(date(2020, 1, 1), date(2020, 1, 31)),))]
    dates = routing.target_dates("ZZZ", today, custom, 30, 90)
    assert all(d >= today for d in dates)
    assert date(2020, 1, 15) not in dates
    assert len(dates) == 61  # rolling only
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_routing.py -k target_dates -v`
Expected: FAIL — `AttributeError: module 'routing' has no attribute 'target_dates'`.

- [ ] **Step 3: Write minimal implementation**

Append to `routing.py`:

```python
def _window_dates(start: date, end: date) -> list[date]:
    out: list[date] = []
    d = start
    while d <= end:
        out.append(d)
        d += timedelta(days=1)
    return out


def target_dates(airport: str, today: date, groups: list[Group],
                 win_min: int, win_max: int) -> list[date]:
    """Rolling window (today+win_min .. today+win_max) UNION the group's window
    dates. Deduplicated, sorted ascending, past dates dropped."""
    dates: set[date] = {today + timedelta(days=n) for n in range(win_min, win_max + 1)}
    g = group_of(airport, groups)
    if g:
        for w in g.windows:
            dates.update(_window_dates(w.start, w.end))
    return sorted(d for d in dates if d >= today)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_routing.py -v`
Expected: PASS (8 passed).

- [ ] **Step 5: Commit**

```bash
git add routing.py tests/test_routing.py
git commit -m "feat(routing): target_dates merges rolling window with group windows"
```

---

### Task 4: `telegram_bot.send_azul_alert` — topic routing + General fallback

**Files:**
- Modify: `telegram_bot.py:108-128` (`send_azul_alert`)
- Test: `tests/test_telegram_bot.py` (add cases)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_telegram_bot.py`:

```python
async def test_send_azul_alert_passes_topic_id(monkeypatch):
    mock_bot = AsyncMock()
    mock_bot.send_message = AsyncMock()
    monkeypatch.setattr(_tb, "get_bot", lambda: mock_bot)
    f = _Flight("CNF", "IGU", "Azul", _date(2026, 7, 15), "12h00", "13h15",
                300.0, True, 0, "https://book")
    comp = _AzulComparison(competitor="LATAM", competitor_price=396.0, savings=96.0)
    result = await _tb.send_azul_alert(f, comp, topic_id=42)
    assert result is True
    assert mock_bot.send_message.call_args.kwargs["message_thread_id"] == 42


async def test_send_azul_alert_no_topic_posts_to_general(monkeypatch):
    mock_bot = AsyncMock()
    mock_bot.send_message = AsyncMock()
    monkeypatch.setattr(_tb, "get_bot", lambda: mock_bot)
    f = _Flight("CNF", "GIG", "Azul", _date(2026, 7, 15), "12h00", "13h15",
                300.0, True, 0, "https://book")
    comp = _AzulComparison(competitor="LATAM", competitor_price=396.0, savings=96.0)
    result = await _tb.send_azul_alert(f, comp)
    assert result is True
    assert mock_bot.send_message.call_args.kwargs["message_thread_id"] is None


async def test_send_azul_alert_falls_back_to_general_on_topic_failure(monkeypatch):
    calls = []

    async def send_message(**kwargs):
        calls.append(kwargs["message_thread_id"])
        if kwargs["message_thread_id"] is not None:
            raise RuntimeError("topic gone")

    mock_bot = MagicMock()
    mock_bot.send_message = send_message
    monkeypatch.setattr(_tb, "get_bot", lambda: mock_bot)
    f = _Flight("CNF", "IGU", "Azul", _date(2026, 7, 15), "12h00", "13h15",
                300.0, True, 0, "https://book")
    comp = _AzulComparison(competitor="LATAM", competitor_price=396.0, savings=96.0)
    result = await _tb.send_azul_alert(f, comp, topic_id=42)
    assert result is True
    assert calls == [42, None]   # tried the topic, then General
```

(`AsyncMock`, `MagicMock`, `_tb`, `_Flight`, `_AzulComparison`, `_date` are already imported at the top/bottom of this test file.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_telegram_bot.py -k "topic or general" -v`
Expected: FAIL — `send_azul_alert()` got an unexpected keyword argument `topic_id`.

- [ ] **Step 3: Write minimal implementation**

Replace the body of `send_azul_alert` in `telegram_bot.py` (currently lines 108-128) with:

```python
async def send_azul_alert(flight: Flight, comparison: AzulComparison,
                          topic_id: int | None = None) -> bool:
    """Returns True if the alert was sent, False otherwise (so the caller only
    marks it as seen on success — a failed send must be retried next cycle).
    Posts to the forum topic `topic_id` when given; if that send fails (topic
    deleted, chat isn't a forum, ...) it retries once on the General thread."""
    message = format_azul_alert(flight, comparison)
    try:
        bot = get_bot()
    except Exception as e:
        logger.error(f"Falha ao criar bot Telegram: {e}")
        return False

    async def _send(thread_id: int | None) -> None:
        await bot.send_message(
            chat_id=TELEGRAM_CHANNEL_ID,
            text=message,
            parse_mode=ParseMode.MARKDOWN,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
            message_thread_id=thread_id,
        )

    try:
        await _send(topic_id)
    except Exception as e:
        if topic_id is None:
            logger.error(f"Falha ao enviar alerta Azul: {e}")
            return False
        logger.warning(f"Tópico {topic_id} falhou, tentando Geral: {e}")
        try:
            await _send(None)
        except Exception as e2:
            logger.error(f"Falha ao enviar alerta Azul (Geral): {e2}")
            return False

    logger.info(
        f"Alerta Azul enviado: {flight.origin}→{flight.destination} "
        f"R${flight.price:.2f} (vs {comparison.competitor} R${comparison.competitor_price:.2f}) "
        f"{flight.departure_date}"
    )
    return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_telegram_bot.py -v`
Expected: PASS — new tests pass and `test_send_azul_alert_swallows_errors` still passes (get_bot raising → returns False).

- [ ] **Step 5: Commit**

```bash
git add telegram_bot.py tests/test_telegram_bot.py
git commit -m "feat(telegram): route alerts to forum topic with General fallback"
```

---

### Task 5: `cycle.py` — use `routing`, thread `topic_id` through

**Files:**
- Modify: `cycle.py` (whole file)
- Test: `tests/test_cycle.py` (rewrite: drop moved route/date tests, fix run-cycle tests)

- [ ] **Step 1: Update the tests first (they will fail)**

Replace the entire contents of `tests/test_cycle.py` with:

```python
from datetime import date

import cache
import telegram_bot
import cycle
from airlines.base import Flight
from airlines.google_flights import GoogleFlightsSearcher


def _canned(dest="GIG"):
    d = date(2026, 7, 15)
    return [
        Flight("CNF", dest, "Azul", d, "12h00", "13h15", 300.0, True, 0, "u"),
        Flight("CNF", dest, "LATAM", d, "07h00", "08h15", 396.0, True, 0, "u"),
    ]


async def test_run_cycle_sends_alert_when_azul_cheapest(monkeypatch):
    await cache.init_db()
    canned = _canned("GIG")

    async def fake_search_dates(self, origin, destination, dates, batch_size=7):
        return canned if (origin, destination) == ("CNF", "GIG") else []

    monkeypatch.setattr(GoogleFlightsSearcher, "search_dates", fake_search_dates)

    sent = []

    async def fake_send(flight, comparison, topic_id=None):
        sent.append((flight, comparison, topic_id))
        return True

    monkeypatch.setattr(telegram_bot, "send_azul_alert", fake_send)

    await cycle.run_azul_cycle()

    assert len(sent) == 1
    flight, comp, topic_id = sent[0]
    assert "azul" in flight.airline.lower()
    assert comp.competitor == "LATAM"
    assert topic_id is None   # Rio group has no topic configured


async def test_run_cycle_dedups_within_ttl(monkeypatch):
    await cache.init_db()
    canned = _canned("GIG")

    async def fake_search_dates(self, origin, destination, dates, batch_size=7):
        return canned if (origin, destination) == ("CNF", "GIG") else []

    monkeypatch.setattr(GoogleFlightsSearcher, "search_dates", fake_search_dates)
    sent = []

    async def fake_send(flight, comparison, topic_id=None):
        sent.append(flight)
        return True

    monkeypatch.setattr(telegram_bot, "send_azul_alert", fake_send)

    await cycle.run_azul_cycle()
    await cycle.run_azul_cycle()   # same flight, must be deduped

    assert len(sent) == 1


async def test_run_cycle_retries_when_send_fails(monkeypatch):
    await cache.init_db()
    canned = _canned("GIG")

    async def fake_search_dates(self, origin, destination, dates, batch_size=7):
        return canned if (origin, destination) == ("CNF", "GIG") else []

    monkeypatch.setattr(GoogleFlightsSearcher, "search_dates", fake_search_dates)
    attempts = []

    async def failing_send(flight, comparison, topic_id=None):
        attempts.append(flight)
        return False   # failed send → must NOT be cached

    monkeypatch.setattr(telegram_bot, "send_azul_alert", failing_send)

    await cycle.run_azul_cycle()
    await cycle.run_azul_cycle()   # failed before → retried, not deduped

    assert len(attempts) == 2
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_cycle.py -v`
Expected: FAIL — `fake_send`/`failing_send` take `topic_id`, but `cycle.run_azul_cycle` still calls `send_azul_alert(flight, comparison)` with only 2 args, so the alert count assertions break (or it still searches `("CNF","SSA")` which is no longer a route). Either way: not all pass.

- [ ] **Step 3: Rewrite `cycle.py`**

Replace the entire contents of `cycle.py` with:

```python
import logging
from datetime import date

import cache
import telegram_bot
import routing
from airlines.google_flights import GoogleFlightsSearcher
from alerts import evaluate
from config import (
    AZUL_HUB, GROUPS, WINDOW_MIN_DAYS, WINDOW_MAX_DAYS,
    BATCH_SIZE, CACHE_TTL_HOURS,
)

logger = logging.getLogger(__name__)

_searcher = GoogleFlightsSearcher()


async def run_azul_cycle() -> None:
    today = date.today()
    await cache.purge_expired()
    total_alerts = 0
    total_errors = 0

    for route in routing.build_routes(GROUPS, AZUL_HUB):
        dates = routing.target_dates(
            route.non_hub, today, GROUPS, WINDOW_MIN_DAYS, WINDOW_MAX_DAYS
        )
        try:
            flights = await _searcher.search_dates(
                route.origin, route.destination, dates, BATCH_SIZE
            )
        except Exception as e:
            logger.warning(f"AZUL {route.origin}→{route.destination}: erro na busca: {e}")
            total_errors += 1
            continue

        alerts = evaluate(flights)
        for alert in alerts:
            if not await cache.is_cached(alert.flight):
                sent = await telegram_bot.send_azul_alert(
                    alert.flight, alert.comparison, route.topic_id
                )
                if sent:
                    await cache.save_to_cache(alert.flight, CACHE_TTL_HOURS)
                    total_alerts += 1

        logger.info(
            f"AZUL {route.origin}→{route.destination}: {len(flights)} voos, "
            f"{len(alerts)} datas com Azul mais barata"
        )

    logger.info(f"CICLO AZUL CONCLUÍDO — alertas: {total_alerts} | erros: {total_errors}")
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_cycle.py tests/test_routing.py -v`
Expected: PASS (3 cycle + 8 routing).

- [ ] **Step 5: Commit**

```bash
git add cycle.py tests/test_cycle.py
git commit -m "refactor(cycle): drive from routing.GROUPS and thread topic_id to send"
```

---

### Task 6: Remove dead config constants (`AZUL_DESTINATIONS`, `AZUL_DATE_OVERRIDES`)

**Files:**
- Modify: `config.py` (delete the two superseded constants)

- [ ] **Step 1: Confirm nothing references them anymore**

Run: `python -c "import subprocess,sys; sys.exit(0)"` then grep:
Run: `grep -rn "AZUL_DESTINATIONS\|AZUL_DATE_OVERRIDES" --include=*.py .`
Expected: **no matches** outside `config.py` itself (the only remaining hits are the two definition lines you are about to delete). If any `.py` outside `config.py` matches, stop and fix that reference first.

- [ ] **Step 2: Delete the constants**

In `config.py`, remove the `AZUL_DESTINATIONS = [...]` block and the `AZUL_DATE_OVERRIDES = {}` line (and their comments). Keep `AZUL_HUB`, `WINDOW_MIN_DAYS`, `WINDOW_MAX_DAYS`, `BATCH_SIZE`, `CACHE_TTL_HOURS`, the `GROUPS`/model from Task 1, and the dormant `MILES_*` config.

- [ ] **Step 3: Verify import + full suite**

Run: `python -c "import config, routing, cycle, telegram_bot; print('imports ok', len(config.GROUPS), 'groups')"`
Expected: `imports ok 10 groups`

Run: `python -m pytest -q`
Expected: all tests PASS.

- [ ] **Step 4: Commit**

```bash
git add config.py
git commit -m "refactor(config): drop AZUL_DESTINATIONS/AZUL_DATE_OVERRIDES (superseded by GROUPS)"
```

---

### Task 7: `scripts/list_topics.py` — discover forum topic ids

**Files:**
- Create: `scripts/list_topics.py`

This is a one-off operator tool (not run in CI; `scripts/` is excluded from `testpaths`). It is verified by a syntax/parse check, not a unit test.

- [ ] **Step 1: Create the script**

Create `scripts/list_topics.py`:

```python
"""One-off helper: print Telegram forum topic (thread) ids.

Usage:
  1. Make the bot an admin in your Forum-enabled supergroup.
  2. In EACH topic, send a short message naming it (e.g. "foz", "patagonia").
  3. Run:  python scripts/list_topics.py
  4. Map the printed thread_id to each message text, then paste the ids into the
     matching Group(topic_id=...) entries in config.py.

Requires TELEGRAM_BOT_TOKEN in the environment (or .env).
Note: if the bot has a webhook set, get_updates() will fail — remove it first
(`Bot.delete_webhook()`), or read the ids from the Telegram app's topic links.
"""
import asyncio
import os

from dotenv import load_dotenv
from telegram import Bot

load_dotenv()


async def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise SystemExit("Defina TELEGRAM_BOT_TOKEN (no .env) antes de rodar.")

    bot = Bot(token=token)
    updates = await bot.get_updates(timeout=5)
    if not updates:
        print("Nenhuma mensagem recente. Mande uma mensagem em cada tópico e rode de novo.")
        return

    print(f"{'chat_id':>16}  {'thread_id':>10}  texto")
    print("-" * 46)
    seen: set[tuple[int, object]] = set()
    for u in updates:
        msg = u.message or u.channel_post
        if not msg:
            continue
        key = (msg.chat_id, msg.message_thread_id)
        if key in seen:
            continue
        seen.add(key)
        text = (msg.text or "").replace("\n", " ")[:30]
        print(f"{msg.chat_id:>16}  {str(msg.message_thread_id):>10}  {text}")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Verify it parses and imports cleanly**

Run: `python -c "import ast; ast.parse(open('scripts/list_topics.py', encoding='utf-8').read()); print('parse ok')"`
Expected: `parse ok`

- [ ] **Step 3: Commit**

```bash
git add scripts/list_topics.py
git commit -m "feat(scripts): list_topics.py to discover forum topic ids"
```

---

### Task 8: Raise GitHub Actions job timeout

**Files:**
- Modify: `.github/workflows/azul-alert.yml:15`

The added far-future window queries (~+400/pass) push runtime up; give margin under the 30-min cap.

- [ ] **Step 1: Edit the timeout**

In `.github/workflows/azul-alert.yml`, change:

```yaml
    timeout-minutes: 30
```

to:

```yaml
    timeout-minutes: 60
```

- [ ] **Step 2: Verify the change**

Run: `grep -n "timeout-minutes" .github/workflows/azul-alert.yml`
Expected: `    timeout-minutes: 60`

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/azul-alert.yml
git commit -m "ci: raise azul-alert timeout to 60min for window queries"
```

---

### Task 9: Final verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full suite**

Run: `python -m pytest -q`
Expected: all tests PASS, no warnings about missing symbols.

- [ ] **Step 2: Smoke-check the wiring end to end (no network, no Telegram)**

Run:
```bash
python -c "import config, routing; rs = routing.build_routes(config.GROUPS, config.AZUL_HUB); print('routes', len(rs)); from datetime import date; print('IGU dates', len(routing.target_dates('IGU', date.today(), config.GROUPS, config.WINDOW_MIN_DAYS, config.WINDOW_MAX_DAYS)))"
```
Expected: `routes 42` and an `IGU dates` count of `61` plus the in-range days of the Oct-2026 window (i.e. > 61 while that window is still in the future; exactly `61` once Oct 2026 has passed).

- [ ] **Step 3: Confirm clean tree**

Run: `git status --short`
Expected: empty (everything committed).

---

## Post-merge operator setup (manual, not code)

After this branch is merged and deployed, to actually use topics:

1. Turn the alert destination into a **Forum-enabled supergroup** (Telegram → group → Edit → *Topics* ON). Topics don't exist in channels, so a channel-only `TELEGRAM_CHANNEL_ID` must become a forum supergroup id (`-100…`). Update the `TELEGRAM_CHANNEL_ID` secret/env.
2. Add the bot as **admin** in that supergroup.
3. Create the topics you want (Foz do Iguaçu, Patagônia, Portugal, ...).
4. Send a message in each topic, run `python scripts/list_topics.py`, and paste each `thread_id` into the matching `Group(..., topic_id=<id>)` in `config.py`. Commit.

Until step 4, every `topic_id` stays `None` and all alerts land in the General thread — the bot keeps working unchanged.

---

## Self-Review

**1. Spec coverage**
- Region groups replacing flat list → Task 1 (`GROUPS`), Task 6 (remove old). ✓
- SSA removed, Europe added (2 airports each) → Task 1 + tests. ✓
- Additive windows (rolling always on) → Task 3 `target_dates` + tests. ✓
- `month()` helper, past-date drop, dedup → Task 1 + Task 3 + tests. ✓
- Routes from groups, both directions, carry topic_id → Task 2 + Task 5. ✓
- Telegram topic via `message_thread_id` + General fallback → Task 4 + tests. ✓
- Backwards compatible (all `topic_id=None` → today's behaviour) → Task 4 default arg + Task 1 defaults + tests. ✓
- `list_topics.py` onboarding helper → Task 7. ✓
- Timeout bump → Task 8. ✓
- Tests for all logic + update existing → Tasks 1-5, 9. ✓

**2. Placeholder scan:** No TBD/TODO; every code/test step shows full code; every run step shows command + expected output. ✓

**3. Type consistency:** `SearchWindow(start,end)`, `month(year,m)`, `Group(name, airports, windows=(), topic_id=None)`, `Route(origin, destination, non_hub, topic_id)`, `group_of(airport, groups)`, `build_routes(groups, hub)`, `target_dates(airport, today, groups, win_min, win_max)`, `send_azul_alert(flight, comparison, topic_id=None)` — names/signatures used identically across Tasks 1-9 and match the spec. ✓
