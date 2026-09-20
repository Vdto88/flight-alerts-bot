# 180-day search window — design

Date: 2026-09-20
Status: approved in chat, pending spec review
Branch: `feat/window-180`

## Problem

The bot looks 30 to 120 days ahead. The owner wants 180. A cycle already takes 29–34 minutes
for about 6,200 queries against a 60-minute job limit; 180 days means about 8,500 queries and
roughly 45 minutes. Two things found while measuring shape the design:

- About 13% of queries fail on the runner with `Network is unreachable (os error 101)` and are
  never retried. Recovering them is worth more data than the wider window.
- `history.enc.json` is one file for every route. It is 242 KB today and heads for several MB
  as series fill up and the window grows; the panel needs one route at a time.

The owner chose: far dates once a day is enough. No parallel jobs.

## Out of scope

- Splitting the cycle into parallel jobs.
- Filtering or digesting alerts.
- `history.route_stats()` reading every live row. Measured on the first real run; becomes
  work only if it costs more than a few seconds or the runner's memory.
- The classic panel (it does not read history files).

## 1. Two date bands (`config.py`, `routing.py`, `cycle.py`, `main.py`)

- `WINDOW_MIN_DAYS = 30`, `WINDOW_MAX_DAYS = 120` stay: the **near band**, searched every cycle.
- New `WINDOW_FAR_MAX_DAYS = 180`: the **far band** is `WINDOW_MAX_DAYS + 1 .. WINDOW_FAR_MAX_DAYS`.
- Explicit windows (group months, price-watch months, the round-trip span) are unchanged and
  searched every cycle, even when they overlap the far band.
- `routing.target_dates(...)` gains `far_max: int | None = None`. With a value, the rolling
  range becomes `win_min .. far_max`; with `None` it stays `win_min .. win_max`.
- `run_azul_cycle(include_far: bool = False)`. `main.py` reads `SEARCH_FAR_DATES`: `"1"` →
  `True`, anything else → `False`.
- The workflow's single cron entry (`0 11,17,23 * * *`) is split in two, `0 11 * * *` and
  `0 17,23 * * *`, because `github.event.schedule` carries the whole cron string of the entry
  that fired and cannot tell the hours of one entry apart.
- Workflow sets `SEARCH_FAR_DATES: "1"` when `github.event_name == 'workflow_dispatch'` or
  `github.event.schedule == '0 11 * * *'` (08:00 BRT), else `"0"`. `timeout-minutes` 60 → 90.

## 2. Far dates stay in the panel between far cycles (`far_cache.py`, new)

The snapshot is rebuilt from the flights searched in that cycle, so far-band deals would
appear in the morning and vanish in the afternoon.

- `data/far_deals.json` (inside the `data/` directory that `actions/cache` persists; it is not
  part of the release backup, and losing it only hides far dates until the next far cycle) holds the far-band
  panel records of the last far cycle: `{"visto_em": ISO-UTC, "deals": [...]}`.
- A deal is **far-band** when its `data` is later than `today + WINDOW_MAX_DAYS` and it is
  not a round-trip record.
- Far cycle: after building `all_deals`, write the far-band subset with `visto_em = now`.
- Near cycle: load the file; keep records whose `data` is still later than
  `today + WINDOW_MAX_DAYS` (a date that slid into the near band is already covered by the
  live search) and whose key (`origem|destino|data`) is not already in `all_deals` (explicit
  windows win); stamp each with `"visto_em"`; append them to `all_deals` **after** alerts are
  evaluated and **before** `enrich_with_history`, so they get history fields but never fire
  or re-fire an alert.
- Carried records are **not** passed to `history.record`: they were recorded by the cycle that
  found them. `cycle.py` records only the deals it searched.
- The file is discarded when `visto_em` is older than 36 hours (a missed far cycle must not
  leave stale fares in the panel). Missing, unreadable or malformed file → treated as empty,
  warning logged, never raises.
- Signal flags (`azul_cheapest`, `price_watch`) travel with the carried record as computed by
  the far cycle.
- Panel: a record with `visto_em` shows its age in the pass body and the table tooltip
  ("visto há 9 h"); no other UI change.

## 3. Retry failed queries (`airlines/google_flights.py`)

- `search()` retries up to `MAX_RETRIES = 2` more times when the fetch raises, sleeping
  `RETRY_BACKOFF_S * attempt` (1 s, 2 s) with `asyncio.sleep`. Only the fetch is retried;
  a parsed empty result is a valid answer.
- The first failures log at DEBUG; only the final one logs the existing WARNING, so the log
  stops carrying ~800 lines a cycle.
- The searcher counts queries and final failures. The cycle summary line gains
  `consultas: N | falhas: M`. If `M / N > 0.5` on a non-empty cycle, send one
  `telegram_bot.send_health_alert` ("mais da metade das consultas falhou"); the run stays green.

## 4. History files per route (`panel.py`, `scripts/encrypt_deals.py`, `web/app.js`, workflow)

- `panel.write_history_files(payload, out_dir)` replaces `write_history`: writes
  `history/<ORIG>-<DEST>.json`, each `{"gerado_em", "rota": {...route summary...},
  "series": {"ORIG|DEST|DATE": [[dia, price], ...]}}` with only that route's keys. The
  directory is emptied first so dropped routes do not linger.
- A route present in `series` but absent from `route_stats` (first seen this cycle) still gets
  a file, with `"rota": null`.
- `encrypt_deals.py` CLI encrypts every `history/*.json` to `history/*.enc.json` (v2), then
  deletes the plaintext. `cycle.HISTORY_PATH` becomes `HISTORY_DIR = "history"`.
- `.gitignore`: `history/` replaces `history.json` / `history.enc.json`.
- Workflow "Assemble site": `mkdir -p _site/history && cp history/*.enc.json _site/history/`
  (guarded for an empty directory); the old single-file copy is removed.
- `web/app.js`: `ensureHistory()` becomes `ensureRouteHistory(origem, destino)`, keyed cache of
  promises, one fetch per route per session, called for the routes of the open passes.
  `dateChart` and `routeSection` read that route's payload. A missing file (404) degrades to the
  existing "Histórico indisponível" notice for that pass only. `rota: null` → chart shown,
  route section omitted.

## 5. Alerts

Far-band dates go through the same three signals in the far cycle. Expect the 08:00 BRT cycle
to send proportionally more alerts. Dedup keys and TTL are unchanged.

## 6. Error handling

| Failure | Behaviour |
|---|---|
| `far_deals.json` missing / corrupt / older than 36 h | treated as empty; warning; cycle continues |
| Writing `far_deals.json` fails | error logged; cycle continues |
| A query fails after all retries | WARNING as today; counted in `falhas` |
| More than half of the queries fail | one health alert; run stays green |
| A route's history file is missing in the panel | notice in that pass; others unaffected |
| `history/` write fails | error logged; `deals.json` still written and deployed |

## 7. Testing

- `routing.target_dates`: near-only vs `far_max`; explicit windows unaffected.
- `main`/`cycle`: `SEARCH_FAR_DATES` parsing; `include_far` reaches `target_dates`.
- `far_cache`: far-band predicate at the boundary day; save on far cycle; merge on near cycle
  (drops dates that slid into the near band, drops keys already present, stamps `visto_em`);
  stale file discarded at 36 h; corrupt file tolerated; carried records are not recorded into
  history and fire no alert.
- `google_flights.search`: succeeds on the 2nd and 3rd attempt; gives up after 3 with one
  WARNING; counters; `asyncio.sleep` patched so tests stay fast.
- `cycle`: summary counters; health alert above 50% failures, none below.
- `panel.write_history_files`: one file per route, only that route's series, `rota: null`
  case, stale files removed.
- `encrypt_deals` CLI: every history file encrypted, plaintext removed.
- Browser (fixture): opening two passes of different routes fetches two files once each;
  404 on one route degrades only that pass; carried record shows its age; 375 px; classic
  panel still unlocks.

## 8. Rollout

1. Merge and push; trigger one manual run (far band included).
2. Check the log: duration under 90 min, `consultas`/`falhas` counts, failure rate well under
   13%, `far_deals.json` written, route_stats timing.
3. Check Pages: `history/` files present, old `history.enc.json` gone, panel chart loads.
4. After the next scheduled near cycle: far-band dates still in the panel with an age.
