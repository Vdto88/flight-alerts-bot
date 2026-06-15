# Price-Watch Threshold Alerts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a second, independent alert that fires when the cheapest fare (any airline) for a watched airport, within a specific month, is `<=` a configured BRL limit — reusing the flights already fetched per cycle (no extra Google queries).

**Architecture:** A declarative `PRICE_WATCHES` list (`config.py`) of `PriceWatch(airport, window, max_price)`. `routing.target_dates` also searches each watch's month. A pure `alerts.evaluate_threshold` finds, per date in a watch window, the cheapest fare `<=` the limit. `cycle.py` runs it on the same flights as the Azul check and sends via a new `telegram_bot.send_price_alert` to the destination's region topic. Price alerts dedup in a separate cache namespace (`kind="price"`) so they never collide with Azul alerts.

**Tech Stack:** Python 3.11, `python-telegram-bot==21.3.0`, `aiosqlite`, `pytest`/`pytest-asyncio` (`asyncio_mode=auto`).

**Working dir:** All paths relative to `C:\FlightAlert`, branch `feature/price-watch-alerts`. Run tests with `python -m pytest` from that root.

**Commits:** Every commit message must end with:
`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`

**Spec:** `docs/superpowers/specs/2026-06-15-price-watch-threshold-alerts-design.md`

---

## File Structure

| File | Responsibility | Action |
|------|----------------|--------|
| `config.py` | Declarative data: add `PriceWatch` + `PRICE_WATCHES`. | Modify |
| `airlines/base.py` | `Flight.cache_key(kind="")` — namespace prefix. | Modify |
| `cache.py` | `is_cached`/`save_to_cache` accept `kind=""`. | Modify |
| `alerts.py` | `ThresholdAlert` + pure `evaluate_threshold`. | Modify |
| `routing.py` | `target_dates(..., watches=())` unions watch windows. | Modify |
| `telegram_bot.py` | `format_price_alert` + `send_price_alert(..., topic_id=None)`. | Modify |
| `cycle.py` | Run `evaluate_threshold` on the same flights; send price alerts; price-namespace dedup. | Modify |
| `tests/` | New `test_price_watches.py`, `test_threshold.py`; append to `test_base.py`, `test_cache.py`, `test_routing.py`, `test_telegram_bot.py`, `test_cycle.py`. | Create/Modify |

**Ordering:** every change is *additive* with safe defaults (`kind=""`, `watches=()`), so the suite stays green after each task. The integration in `cycle.py` (Task 7) comes last, after every piece it calls exists.

---

### Task 1: `config.py` — `PriceWatch` + `PRICE_WATCHES`

**Files:**
- Modify: `config.py`
- Test: `tests/test_price_watches.py` (create)

- [ ] **Step 1: Write the failing test.** Create `tests/test_price_watches.py`:

```python
from datetime import date
import config


def test_price_watch_fields():
    w = config.PriceWatch("SJK", config.month(2026, 9), 400.0)
    assert w.airport == "SJK"
    assert w.window == config.SearchWindow(date(2026, 9, 1), date(2026, 9, 30))
    assert w.max_price == 400.0


def test_price_watches_seed_entry_is_in_a_group():
    # Every watched airport must belong to some Group (for routing + topic).
    group_airports = {a for g in config.GROUPS for a in g.airports}
    for w in config.PRICE_WATCHES:
        assert w.airport in group_airports, f"{w.airport} is watched but in no Group"


def test_price_watches_has_sjk_september_example():
    by_airport = {w.airport: w for w in config.PRICE_WATCHES}
    assert "SJK" in by_airport
    assert by_airport["SJK"].window == config.month(2026, 9)
    assert by_airport["SJK"].max_price == 400.0
```

- [ ] **Step 2: Run — expect FAIL.** `python -m pytest tests/test_price_watches.py -v` → `AttributeError: module 'config' has no attribute 'PriceWatch'`.

- [ ] **Step 3: Implement.** In `config.py`, add the dataclass right after the `Group` class definition, and the list right after `GROUPS`:

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

- [ ] **Step 4: Run — expect PASS.** `python -m pytest tests/test_price_watches.py -v` → 3 passed.

- [ ] **Step 5: Full suite stays green.** `python -m pytest -q` → all pass.

- [ ] **Step 6: Commit.**
```bash
git add config.py tests/test_price_watches.py
git commit -m "feat(config): add PriceWatch model and PRICE_WATCHES"
```

---

### Task 2: `Flight.cache_key(kind="")` — namespace prefix

**Files:**
- Modify: `airlines/base.py:33-38`
- Test: `tests/test_base.py` (append)

- [ ] **Step 1: Write the failing test.** Append to `tests/test_base.py`:

```python
from datetime import date as _d
from airlines.base import Flight as _Flight


def test_cache_key_default_is_unprefixed():
    f = _Flight("CNF", "SJK", "GOL", _d(2026, 9, 10), "08h00", "09h00",
                380.0, True, 0, "u")
    assert f.cache_key() == "GOL|CNF|SJK|2026-09-10|380"


def test_cache_key_kind_prefixes():
    f = _Flight("CNF", "SJK", "GOL", _d(2026, 9, 10), "08h00", "09h00",
                380.0, True, 0, "u")
    assert f.cache_key(kind="price") == "price|" + f.cache_key()
```

- [ ] **Step 2: Run — expect FAIL.** `python -m pytest tests/test_base.py -k cache_key -v` → `cache_key() got an unexpected keyword argument 'kind'`.

- [ ] **Step 3: Implement.** Replace `cache_key` in `airlines/base.py` (lines 33-38) with:

```python
    def cache_key(self, kind: str = "") -> str:
        prefix = f"{kind}|" if kind else ""
        if self.miles is not None:
            miles_floor = (self.miles // 1000) * 1000
            return f"{prefix}{self.airline}|{self.origin}|{self.destination}|{self.departure_date}|{miles_floor}mi"
        price_floor = math.floor(self.price / 10) * 10
        return f"{prefix}{self.airline}|{self.origin}|{self.destination}|{self.departure_date}|{price_floor}"
```

- [ ] **Step 4: Run — expect PASS.** `python -m pytest tests/test_base.py -v` → all pass (existing tests use the default and are unaffected).

- [ ] **Step 5: Commit.**
```bash
git add airlines/base.py tests/test_base.py
git commit -m "feat(base): optional kind prefix on Flight.cache_key"
```

---

### Task 3: `cache.py` — `is_cached`/`save_to_cache` accept `kind`

**Files:**
- Modify: `cache.py` (the `is_cached` and `save_to_cache` functions)
- Test: `tests/test_cache.py` (append)

- [ ] **Step 1: Write the failing test.** Append to `tests/test_cache.py`:

```python
from datetime import date as _date
from airlines.base import Flight as _Flight
import cache as _cache


def _pw_flight():
    return _Flight("CNF", "SJK", "GOL", _date(2026, 9, 10), "08h00", "09h00",
                   380.0, True, 0, "u")


async def test_cache_namespaces_are_independent():
    await _cache.init_db()
    f = _pw_flight()
    await _cache.save_to_cache(f, 24, kind="price")
    assert await _cache.is_cached(f, kind="price") is True
    assert await _cache.is_cached(f) is False   # default (Azul) namespace untouched
```

(The autouse `use_tmp_db` fixture in `tests/conftest.py` already points `cache.DB_PATH` at a temp file.)

- [ ] **Step 2: Run — expect FAIL.** `python -m pytest tests/test_cache.py -k namespaces -v` → `is_cached() got an unexpected keyword argument 'kind'`.

- [ ] **Step 3: Implement.** In `cache.py`, change the two functions to thread `kind` into the key:

```python
async def is_cached(flight: Flight, kind: str = "") -> bool:
    key = flight.cache_key(kind)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM seen_flights WHERE cache_key = ? AND expires_at > ?",
            (key, _now_iso()),
        ) as cursor:
            return await cursor.fetchone() is not None


async def save_to_cache(flight: Flight, ttl_hours: int = 24, kind: str = "") -> None:
    key = flight.cache_key(kind)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO seen_flights (cache_key, detected_at, expires_at) VALUES (?, ?, ?)",
            (key, _now_iso(), _expires_iso(ttl_hours)),
        )
        await db.commit()
```

- [ ] **Step 4: Run — expect PASS.** `python -m pytest tests/test_cache.py -v` → all pass.

- [ ] **Step 5: Commit.**
```bash
git add cache.py tests/test_cache.py
git commit -m "feat(cache): optional kind namespace on is_cached/save_to_cache"
```

---

### Task 4: `alerts.py` — `ThresholdAlert` + `evaluate_threshold`

**Files:**
- Modify: `alerts.py` (append)
- Test: `tests/test_threshold.py` (create)

- [ ] **Step 1: Write the failing test.** Create `tests/test_threshold.py`:

```python
from datetime import date

from airlines.base import Flight
from config import PriceWatch, SearchWindow
from alerts import evaluate_threshold, ThresholdAlert

SEP = SearchWindow(date(2026, 9, 1), date(2026, 9, 30))


def _f(airline, price, d=date(2026, 9, 10)):
    return Flight("CNF", "SJK", airline, d, "08h00", "09h00", price, True, 0, "u")


def test_fires_on_cheapest_any_airline_at_or_under_limit():
    flights = [_f("GOL", 380.0), _f("Azul", 420.0), _f("LATAM", 500.0)]
    alerts = evaluate_threshold(flights, [PriceWatch("SJK", SEP, 400.0)])
    assert len(alerts) == 1
    assert isinstance(alerts[0], ThresholdAlert)
    assert alerts[0].flight.airline == "GOL"
    assert alerts[0].flight.price == 380.0
    assert alerts[0].max_price == 400.0


def test_limit_is_inclusive():
    alerts = evaluate_threshold([_f("GOL", 400.0)], [PriceWatch("SJK", SEP, 400.0)])
    assert len(alerts) == 1


def test_no_fire_above_limit():
    assert evaluate_threshold([_f("GOL", 401.0)], [PriceWatch("SJK", SEP, 400.0)]) == []


def test_ignores_dates_outside_window():
    flights = [_f("GOL", 200.0, date(2026, 10, 5))]   # October, window is September
    assert evaluate_threshold(flights, [PriceWatch("SJK", SEP, 400.0)]) == []


def test_ignores_nonpositive_price():
    assert evaluate_threshold([_f("Azul", 0.0)], [PriceWatch("SJK", SEP, 400.0)]) == []


def test_no_watches_returns_empty():
    assert evaluate_threshold([_f("GOL", 100.0)], []) == []


def test_picks_tightest_satisfied_limit_when_two_watches_overlap():
    watches = [PriceWatch("SJK", SEP, 400.0), PriceWatch("SJK", SEP, 350.0)]
    alerts = evaluate_threshold([_f("GOL", 300.0)], watches)
    assert len(alerts) == 1
    assert alerts[0].max_price == 350.0   # smallest limit the fare still satisfies
```

- [ ] **Step 2: Run — expect FAIL.** `python -m pytest tests/test_threshold.py -v` → `ImportError: cannot import name 'evaluate_threshold'`.

- [ ] **Step 3: Implement.** Append to `alerts.py`:

```python
from config import PriceWatch


@dataclass
class ThresholdAlert:
    flight: Flight        # the cheapest fare on that date (any airline)
    max_price: float      # the watch limit it satisfied


def evaluate_threshold(flights: list[Flight], watches: list[PriceWatch]) -> list[ThresholdAlert]:
    """For one route's flights, return price alerts where the cheapest fare on a date inside
    a watch's window is <= that watch's max_price. Airline-agnostic; ignores price <= 0.
    Emits at most one alert per date (the tightest satisfied limit)."""
    if not watches:
        return []

    by_date: dict = {}
    for f in flights:
        if f.price is None or f.price <= 0:
            continue
        by_date.setdefault(f.departure_date, []).append(f)

    alerts: list[ThresholdAlert] = []
    for d, day_flights in by_date.items():
        cheapest = min(day_flights, key=lambda f: f.price)
        matching = [
            w for w in watches
            if w.window.start <= d <= w.window.end and cheapest.price <= w.max_price
        ]
        if matching:
            best = min(matching, key=lambda w: w.max_price)
            alerts.append(ThresholdAlert(flight=cheapest, max_price=best.max_price))
    return alerts
```

(`alerts.py` already imports `from dataclasses import dataclass` and `from airlines.base import Flight`. `config.py` does not import `alerts`, so importing `PriceWatch` here is not circular.)

- [ ] **Step 4: Run — expect PASS.** `python -m pytest tests/test_threshold.py -v` → 7 passed.

- [ ] **Step 5: Full suite green.** `python -m pytest -q`.

- [ ] **Step 6: Commit.**
```bash
git add alerts.py tests/test_threshold.py
git commit -m "feat(alerts): evaluate_threshold for price-watch alerts"
```

---

### Task 5: `routing.target_dates(..., watches=())`

**Files:**
- Modify: `routing.py` (the `target_dates` function)
- Test: `tests/test_routing.py` (append)

- [ ] **Step 1: Write the failing test.** Append to `tests/test_routing.py`:

```python
def test_target_dates_includes_price_watch_window():
    today = date(2026, 1, 1)
    custom = [config.Group("T", ("ZZZ",))]
    watches = [config.PriceWatch("ZZZ", config.SearchWindow(date(2027, 1, 1), date(2027, 1, 31)), 500.0)]
    dates = routing.target_dates("ZZZ", today, custom, 30, 90, watches)
    assert date(2027, 1, 1) in dates    # a month far outside the rolling window
    assert date(2027, 1, 31) in dates
    assert dates == sorted(dates)


def test_target_dates_ignores_watch_for_other_airport():
    today = date(2026, 1, 1)
    custom = [config.Group("T", ("ZZZ",))]
    watches = [config.PriceWatch("YYY", config.SearchWindow(date(2027, 1, 1), date(2027, 1, 31)), 500.0)]
    dates = routing.target_dates("ZZZ", today, custom, 30, 90, watches)
    assert date(2027, 1, 1) not in dates
    assert len(dates) == 61   # rolling only


def test_target_dates_watches_default_empty():
    today = date(2026, 1, 1)
    dates = routing.target_dates("GIG", today, config.GROUPS, 30, 90)
    assert len(dates) == 61   # unchanged when no watches passed
```

- [ ] **Step 2: Run — expect FAIL.** `python -m pytest tests/test_routing.py -k price_watch -v` → `target_dates() takes ... positional arguments but 6 were given`.

- [ ] **Step 3: Implement.** Replace `target_dates` in `routing.py` with (note the new `watches` param and the new loop; everything else is unchanged):

```python
def target_dates(airport: str, today: date, groups: list[Group],
                 win_min: int, win_max: int, watches=()) -> list[date]:
    """Rolling window (today+win_min .. today+win_max) UNION the airport's group windows
    UNION the windows of any PriceWatch for the airport. Deduped, sorted, past dropped."""
    dates: set[date] = {today + timedelta(days=n) for n in range(win_min, win_max + 1)}
    g = group_of(airport, groups)
    if g:
        for w in g.windows:
            dates.update(_window_dates(w.start, w.end))
    for pw in watches:
        if pw.airport == airport:
            dates.update(_window_dates(pw.window.start, pw.window.end))
    return sorted(d for d in dates if d >= today)
```

- [ ] **Step 4: Run — expect PASS.** `python -m pytest tests/test_routing.py -v` → all pass (existing calls omit `watches`, defaulting to `()`).

- [ ] **Step 5: Commit.**
```bash
git add routing.py tests/test_routing.py
git commit -m "feat(routing): target_dates also searches price-watch windows"
```

---

### Task 6: `telegram_bot.py` — `format_price_alert` + `send_price_alert`

**Files:**
- Modify: `telegram_bot.py` (append two functions)
- Test: `tests/test_telegram_bot.py` (append)

- [ ] **Step 1: Write the failing test.** Append to `tests/test_telegram_bot.py`:

```python
def test_format_price_alert_shows_route_price_airline_and_limit():
    f = _Flight("CNF", "SJK", "GOL", _date(2026, 9, 10), "08h00", "09h00",
                380.0, True, 0, "https://book")
    msg = _tb.format_price_alert(f, 400.0)
    assert "CNF → SJK" in msg
    assert "380,00" in msg
    assert "GOL" in msg
    assert "400,00" in msg          # the configured limit
    assert "PASSAGEM BARATA" in msg.upper()


async def test_send_price_alert_passes_topic_id(monkeypatch):
    mock_bot = AsyncMock()
    mock_bot.send_message = AsyncMock()
    monkeypatch.setattr(_tb, "get_bot", lambda: mock_bot)
    f = _Flight("CNF", "SJK", "GOL", _date(2026, 9, 10), "08h00", "09h00",
                380.0, True, 0, "https://book")
    assert await _tb.send_price_alert(f, 400.0, topic_id=6) is True
    assert mock_bot.send_message.call_args.kwargs["message_thread_id"] == 6


async def test_send_price_alert_falls_back_to_general(monkeypatch):
    calls = []

    async def send_message(**kwargs):
        calls.append(kwargs["message_thread_id"])
        if kwargs["message_thread_id"] is not None:
            raise RuntimeError("topic gone")

    mock_bot = MagicMock()
    mock_bot.send_message = send_message
    monkeypatch.setattr(_tb, "get_bot", lambda: mock_bot)
    f = _Flight("CNF", "SJK", "GOL", _date(2026, 9, 10), "08h00", "09h00",
                380.0, True, 0, "https://book")
    assert await _tb.send_price_alert(f, 400.0, topic_id=6) is True
    assert calls == [6, None]
```

- [ ] **Step 2: Run — expect FAIL.** `python -m pytest tests/test_telegram_bot.py -k price -v` → `module 'telegram_bot' has no attribute 'format_price_alert'`.

- [ ] **Step 3: Implement.** Append to `telegram_bot.py` (reuses the existing `_format_brl` and `_stops_label` helpers):

```python
def format_price_alert(flight: Flight, max_price: float) -> str:
    dep_date = flight.departure_date.strftime("%d/%m/%Y")
    now_str = datetime.now().strftime("%H:%M")
    return (
        f"✈️ *PASSAGEM BARATA DETECTADA*\n\n"
        f"🛫 {flight.origin} → {flight.destination}\n"
        f"💰 {_format_brl(flight.price)}\n"
        f"🎯 abaixo do seu limite de {_format_brl(max_price)}\n"
        f"📅 {dep_date} • {flight.departure_time} → {flight.arrival_time}\n"
        f"🏢 {flight.airline} • {_stops_label(flight)}\n"
        f"🔗 [Reservar agora]({flight.booking_url})\n\n"
        f"⏰ Detectado às {now_str}"
    )


async def send_price_alert(flight: Flight, max_price: float,
                           topic_id: int | None = None) -> bool:
    """Returns True only on a successful send. Posts to the forum topic `topic_id`;
    if that fails it retries once on the General thread."""
    message = format_price_alert(flight, max_price)
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
            logger.error(f"Falha ao enviar alerta de preço: {e}")
            return False
        logger.warning(f"Tópico {topic_id} falhou, tentando Geral: {e}")
        try:
            await _send(None)
        except Exception as e2:
            logger.error(f"Falha ao enviar alerta de preço (Geral): {e2}")
            return False

    logger.info(
        f"Alerta de preço enviado: {flight.origin}→{flight.destination} "
        f"{flight.airline} R${flight.price:.2f} (limite R${max_price:.2f}) {flight.departure_date}"
    )
    return True
```

- [ ] **Step 4: Run — expect PASS.** `python -m pytest tests/test_telegram_bot.py -v` → all pass.

- [ ] **Step 5: Commit.**
```bash
git add telegram_bot.py tests/test_telegram_bot.py
git commit -m "feat(telegram): format_price_alert + send_price_alert with General fallback"
```

---

### Task 7: `cycle.py` — run the threshold check on the same flights

**Files:**
- Modify: `cycle.py`
- Test: `tests/test_cycle.py` (append)

- [ ] **Step 1: Write the failing test.** Append to `tests/test_cycle.py`:

```python
async def test_run_cycle_sends_price_alert_to_region_topic(monkeypatch):
    await cache.init_db()
    d = date(2026, 9, 10)
    canned = [Flight("CNF", "SJK", "GOL", d, "08h00", "09h00", 380.0, True, 0, "u")]

    async def fake_search_dates(self, origin, destination, dates, batch_size=7):
        return canned if (origin, destination) == ("CNF", "SJK") else []

    monkeypatch.setattr(GoogleFlightsSearcher, "search_dates", fake_search_dates)
    monkeypatch.setattr(cycle, "GROUPS", [config.Group("SP", ("SJK",), topic_id=6)])
    monkeypatch.setattr(cycle, "PRICE_WATCHES", [config.PriceWatch("SJK", config.month(2026, 9), 400.0)])

    sent = []

    async def fake_price(flight, max_price, topic_id=None):
        sent.append((flight, max_price, topic_id))
        return True

    monkeypatch.setattr(telegram_bot, "send_price_alert", fake_price)

    await cycle.run_azul_cycle()

    assert len(sent) == 1
    flight, max_price, topic_id = sent[0]
    assert flight.airline == "GOL" and max_price == 400.0 and topic_id == 6


async def test_run_cycle_dedups_price_alert(monkeypatch):
    await cache.init_db()
    d = date(2026, 9, 10)
    canned = [Flight("CNF", "SJK", "GOL", d, "08h00", "09h00", 380.0, True, 0, "u")]

    async def fake_search_dates(self, origin, destination, dates, batch_size=7):
        return canned if (origin, destination) == ("CNF", "SJK") else []

    monkeypatch.setattr(GoogleFlightsSearcher, "search_dates", fake_search_dates)
    monkeypatch.setattr(cycle, "GROUPS", [config.Group("SP", ("SJK",), topic_id=6)])
    monkeypatch.setattr(cycle, "PRICE_WATCHES", [config.PriceWatch("SJK", config.month(2026, 9), 400.0)])

    sent = []

    async def fake_price(flight, max_price, topic_id=None):
        sent.append(flight)
        return True

    monkeypatch.setattr(telegram_bot, "send_price_alert", fake_price)

    await cycle.run_azul_cycle()
    await cycle.run_azul_cycle()
    assert len(sent) == 1   # price namespace dedups the second pass


async def test_run_cycle_azul_and_price_both_fire(monkeypatch):
    await cache.init_db()
    d = date(2026, 9, 10)
    canned = [
        Flight("CNF", "SJK", "Azul", d, "08h00", "09h00", 300.0, True, 0, "u"),
        Flight("CNF", "SJK", "LATAM", d, "07h00", "08h00", 450.0, True, 0, "u"),
    ]

    async def fake_search_dates(self, origin, destination, dates, batch_size=7):
        return canned if (origin, destination) == ("CNF", "SJK") else []

    monkeypatch.setattr(GoogleFlightsSearcher, "search_dates", fake_search_dates)
    monkeypatch.setattr(cycle, "GROUPS", [config.Group("SP", ("SJK",), topic_id=6)])
    monkeypatch.setattr(cycle, "PRICE_WATCHES", [config.PriceWatch("SJK", config.month(2026, 9), 400.0)])

    azul_sent, price_sent = [], []

    async def fake_azul(flight, comparison, topic_id=None):
        azul_sent.append(flight)
        return True

    async def fake_price(flight, max_price, topic_id=None):
        price_sent.append(flight)
        return True

    monkeypatch.setattr(telegram_bot, "send_azul_alert", fake_azul)
    monkeypatch.setattr(telegram_bot, "send_price_alert", fake_price)

    await cycle.run_azul_cycle()
    assert len(azul_sent) == 1   # Azul is cheapest (300 < 450)
    assert len(price_sent) == 1  # 300 <= 400 limit — independent namespaces
```

- [ ] **Step 2: Run — expect FAIL.** `python -m pytest tests/test_cycle.py -k "price or both" -v` → fails (`cycle` has no `PRICE_WATCHES` / `send_price_alert` not invoked).

- [ ] **Step 3: Implement.** Replace the entire contents of `cycle.py` with:

```python
import logging
from datetime import date

import cache
import telegram_bot
import routing
from airlines.google_flights import GoogleFlightsSearcher
from alerts import evaluate, evaluate_threshold
from config import (
    AZUL_HUB, GROUPS, PRICE_WATCHES, WINDOW_MIN_DAYS, WINDOW_MAX_DAYS,
    BATCH_SIZE, CACHE_TTL_HOURS,
)

logger = logging.getLogger(__name__)

_searcher = GoogleFlightsSearcher()


async def run_azul_cycle() -> None:
    today = date.today()
    await cache.purge_expired()
    total_alerts = 0
    total_price_alerts = 0
    total_errors = 0

    for route in routing.build_routes(GROUPS, AZUL_HUB):
        dates = routing.target_dates(
            route.non_hub, today, GROUPS, WINDOW_MIN_DAYS, WINDOW_MAX_DAYS, PRICE_WATCHES
        )
        try:
            flights = await _searcher.search_dates(
                route.origin, route.destination, dates, BATCH_SIZE
            )
        except Exception as e:
            logger.warning(f"AZUL {route.origin}→{route.destination}: erro na busca: {e}")
            total_errors += 1
            continue

        # Signal 1: Azul is the cheapest airline on a date.
        azul_alerts = evaluate(flights)
        for alert in azul_alerts:
            if not await cache.is_cached(alert.flight):
                if await telegram_bot.send_azul_alert(alert.flight, alert.comparison, route.topic_id):
                    await cache.save_to_cache(alert.flight, CACHE_TTL_HOURS)
                    total_alerts += 1

        # Signal 2: cheapest fare (any airline) <= a price-watch limit. Same flights, no extra queries.
        watches = [w for w in PRICE_WATCHES if w.airport == route.non_hub]
        for pa in evaluate_threshold(flights, watches):
            if not await cache.is_cached(pa.flight, kind="price"):
                if await telegram_bot.send_price_alert(pa.flight, pa.max_price, route.topic_id):
                    await cache.save_to_cache(pa.flight, CACHE_TTL_HOURS, kind="price")
                    total_price_alerts += 1

        logger.info(
            f"AZUL {route.origin}→{route.destination}: {len(flights)} voos, "
            f"{len(azul_alerts)} datas com Azul mais barata"
        )

    logger.info(
        f"CICLO AZUL CONCLUÍDO — alertas: {total_alerts} | "
        f"alertas de preço: {total_price_alerts} | erros: {total_errors}"
    )
```

- [ ] **Step 4: Run — expect PASS.** `python -m pytest tests/test_cycle.py -v` → all pass (the existing Azul tests are unaffected: GIG has no watch, so `watches` is empty and the price path is a no-op for them).

- [ ] **Step 5: Full suite green.** `python -m pytest -q`.

- [ ] **Step 6: Commit.**
```bash
git add cycle.py tests/test_cycle.py
git commit -m "feat(cycle): run price-watch threshold check on the same flights"
```

---

### Task 8: Final verification

**Files:** none (verification only)

- [ ] **Step 1: Full suite.** `python -m pytest -q` → all pass, no warnings about missing symbols.

- [ ] **Step 2: Smoke-check the wiring (no network, no Telegram).**

```bash
python -c "import config, routing, cycle, alerts, telegram_bot; from datetime import date; print('watches', len(config.PRICE_WATCHES)); print('SJK dates incl Sep', len(routing.target_dates('SJK', date.today(), config.GROUPS, config.WINDOW_MIN_DAYS, config.WINDOW_MAX_DAYS, config.PRICE_WATCHES)))"
```
Expected: `watches 1` and a positive date count for SJK that includes its September window.

- [ ] **Step 3: Confirm clean tree.** `git status --short` → empty.

---

## Self-Review

**1. Spec coverage**
- `PriceWatch(airport, window, max_price)` + `PRICE_WATCHES` → Task 1. ✓
- Airport must be in a Group → Task 1 test `test_price_watches_seed_entry_is_in_a_group`. ✓
- Cheapest fare (any airline) `<=` limit, inclusive → Task 4 (`evaluate_threshold`, inclusive-boundary test). ✓
- Only dates inside the watch window → Task 4 (`test_ignores_dates_outside_window`). ✓
- Watch window added to searched dates (even outside rolling) → Task 5. ✓
- Both directions → Task 7 (routes are both directions; `watches` filtered by `route.non_hub`, which is the airport for both). ✓
- Region topic + General fallback → Task 6 (`send_price_alert`) + Task 7 (`route.topic_id`). ✓
- Independent dedup namespace, 24h → Task 2 + Task 3 + Task 7 (`kind="price"`); coexistence proven by `test_run_cycle_azul_and_price_both_fire`. ✓
- No extra Google queries → Task 7 reuses `flights`. ✓
- Backwards compatible (empty `PRICE_WATCHES`, default `kind=""`/`watches=()`) → defaults throughout; existing suite stays green. ✓
- Tests for every piece → Tasks 1-7. ✓

**2. Placeholder scan:** No TBD/TODO; every code/test step shows full code; every run step shows command + expected result. ✓

**3. Type consistency:** `PriceWatch(airport, window, max_price)`, `SearchWindow(start, end)`, `month(y, m)`, `ThresholdAlert(flight, max_price)`, `evaluate_threshold(flights, watches)`, `Flight.cache_key(kind="")`, `is_cached(flight, kind="")`, `save_to_cache(flight, ttl_hours=24, kind="")`, `target_dates(airport, today, groups, win_min, win_max, watches=())`, `format_price_alert(flight, max_price)`, `send_price_alert(flight, max_price, topic_id=None)` — names/signatures used identically across Tasks 1-8 and match the spec. ✓
