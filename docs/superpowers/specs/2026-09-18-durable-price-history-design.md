# Durable price history — design

Date: 2026-09-18
Status: approved in chat, pending spec review
Branch: `feat/durable-price-history`

## Problem

The bot records prices in `data/cache.db`, which only survives through `actions/cache`.
That cache is evicted after 7 idle days, so a short pause erases the whole baseline.
History also keeps just 30 days, one row per cycle, keyed by route + departure date, so it can
answer one question only: "is this exact date cheaper than it was recently?".

The owner wants history to answer four questions:

1. Is this date cheap? (exists today; make it durable and longer)
2. What does this route usually cost? (typical price, cheapest months and weekdays, floor)
3. When should I buy? (price by lead time before departure)
4. A real chart in the panel, instead of the 14-point sparkline.

Telegram alerts keep firing exactly as today; they gain one line of historical context.

## Out of scope

- Extending the search window to 180 days and splitting the cycle into parallel jobs. That is
  the next step. This design is **sized for** 180 days (about 8,500 live route+date keys).
- Filtering or digesting alerts. Volume stays the same.
- New features in the classic panel (`web/classic/`). It keeps the fields it already reads;
  its only change is the shared decompression step from section 3.
- Round-trip records. As today, their total is not comparable with one-way history.

## Approach

Two-layer sqlite database, backed up to a GitHub Release asset, plus a second encrypted file
that carries history to the panel on demand.

Rejected: putting all series inside `deals.enc.json` (already 4 MB, downloaded on every
open); shipping the whole database to the browser (tens of MB on mobile).

## 1. Database (`history.py`)

### 1.1 Detail layer: `price_history` becomes one row per key per day

```sql
CREATE TABLE price_daily (
    route     TEXT NOT NULL,   -- "ORIG|DEST|YYYY-MM-DD" (history.deal_key, unchanged)
    dia       TEXT NOT NULL,   -- observation day, UTC, "YYYY-MM-DD"
    price     REAL NOT NULL,   -- lowest fare seen that day
    PRIMARY KEY (route, dia)
) WITHOUT ROWID;
```

`record(deals)` upserts and keeps the minimum:

```sql
INSERT INTO price_daily (route, dia, price) VALUES (?, ?, ?)
ON CONFLICT (route, dia) DO UPDATE SET price = MIN(price, excluded.price);
```

Three cycles a day collapse into one row, so volume drops to a third.
A row lives while its departure date is in the future. Steady state at 180 days: up to
about 1.5 M rows.

**Migration.** `init_db()` creates `price_daily`; if the old `price_history` table exists it
runs once:
`INSERT OR IGNORE INTO price_daily SELECT route, substr(seen_at,1,10), MIN(price) FROM price_history GROUP BY 1, 2`
then `DROP TABLE price_history`. Idempotent; covered by a test.

### 1.2 Permanent layer: `closed_dates`

When a departure date has passed, its series is summarised and the detail deleted.

```sql
CREATE TABLE closed_dates (
    origem      TEXT NOT NULL,
    destino     TEXT NOT NULL,
    data_voo    TEXT NOT NULL,     -- departure date
    lead_bucket INTEGER NOT NULL,  -- index into LEAD_BUCKETS
    min_price   REAL NOT NULL,     -- lowest daily price seen inside that bucket
    n_obs       INTEGER NOT NULL,  -- days observed inside that bucket
    PRIMARY KEY (origem, destino, data_voo, lead_bucket)
) WITHOUT ROWID;
```

`LEAD_BUCKETS = [(0,7), (8,14), (15,30), (31,60), (61,90), (91,120), (121,180)]`
Lead time = `data_voo − dia` in days. Observations beyond 180 days fall in the last bucket.

`rollup_closed(today)` replaces `purge_old()`: for every `price_daily` key whose departure
date `< today`, write its bucket rows to `closed_dates` (`INSERT OR REPLACE`), then delete the
detail rows. One transaction. Growth: at most 7 rows per route per departure date, about
120k rows a year at 46 routes. Never purged.

Month and weekday of the flight are derived from `data_voo` at query time; medians are
computed in Python, so nothing un-mergeable is stored.

### 1.3 Queries

- `stats(days=60)` — per route+date: `min`, `med`, `spark` (last 14 daily points), `since`
  (the day the current minimum was first seen), `n` (days observed). Same shape as today plus
  `since` and `n`; window grows from 30 to 60 days. Still excludes today, because the cycle
  reads stats before recording.
- `route_stats()` — per `ORIG|DEST`, merging live `price_daily` and `closed_dates`:
  `med` (median of per-date minimums), `min`, `n_dates`, `by_month` (flight month → median),
  `by_dow` (flight weekday → median), `lead_curve` (bucket → median of `min_price`, plus the
  number of closed dates behind it).
- `all_series(max_points=90)` — daily series of every live route+date, oldest first; this is
  what `history.json` ships.

One sqlite connection per call is kept (existing pattern); `record` uses `executemany`.

## 2. Durability (`scripts/history_backup.py` + workflow)

A fixed release tagged `history-db` holds one asset, `cache.db.gz.enc`.

- **Restore (start of run).** After `actions/cache` restore, if `data/cache.db` is missing:
  `python scripts/history_backup.py restore`. Downloads the asset with `gh release download`,
  decrypts, gunzips into `data/cache.db`. Missing release, missing asset or any failure logs a
  warning and the cycle starts empty. Never fails the job.
- **Backup (end of run).** `python scripts/history_backup.py backup`: gzip, encrypt, then
  `gh release upload history-db cache.db.gz.enc --clobber`; creates the release on first use.
  Step has `continue-on-error: true` and runs only when the cycle succeeded, so an empty or
  failed cycle never overwrites a good backup.
- **Encryption.** Reuses `scripts/encrypt_deals.py` (PBKDF2-SHA256, AES-GCM, `PANEL_PASSWORD`),
  refactored to expose `encrypt_bytes` / `decrypt_bytes`. The repository is public, so
  nothing leaves the runner unencrypted.
- **Workflow.** `permissions.contents` goes from `read` to `write`; `GH_TOKEN: ${{ github.token }}`
  on the two steps. The dedup table `seen_flights` lives in the same file and travels along.

## 3. Panel outputs (`panel.py`, `scripts/encrypt_deals.py`)

- `deals.json` keeps its shape. `enrich_with_history` additionally sets, per one-way deal:
  `hist_dias` (n), `hist_desde` (since), and from `route_stats`: `rota_med`, `rota_min`,
  `rota_delta_pct` (fare vs `rota_med`). A date with fewer than two observations still gets
  the route-level fields, so a never-seen date already has a verdict. Existing fields
  (`hist_min`, `hist_med`, `spark`, `delta_pct`, `menor_hist`) are unchanged, so the classic
  panel keeps working.
- New `history.json` → `history.enc.json`:
  `{"gerado_em", "rotas": {"CNF|GIG": {med, min, n_dates, by_month, by_dow, lead_curve}},
    "series": {"CNF|GIG|2026-11-20": [[dia, price], ...]}}`
  Series are capped at the last 90 points per key.
- **Compression.** Both files are gzipped before encryption; payload gets `"v": 2,
  "enc": "gzip"`. The panel reads `v`: for 2 it pipes the plaintext through
  `DecompressionStream("gzip")`; `v: 1` keeps working, so a stale cached page cannot break.
  The decrypt-and-inflate routine moves into `web/switch.js`, which both panels already
  load, so the new and the classic panel share one implementation.
  Expected effect: `deals.enc.json` from about 4 MB to about 0.5 MB.
- The workflow's "Assemble site" step copies `history.enc.json` next to `deals.enc.json`.

## 4. Cycle and Telegram (`cycle.py`, `telegram_bot.py`)

- `run_azul_cycle` order becomes: `init_db` → `rollup_closed(today)` → load `stats()` and
  `route_stats()` once → search loop (alerts use the loaded stats) → `enrich` → `record` →
  write `deals.json` and `history.json`. Recording stays last, so today's prices never skew
  the baseline they are compared against.
- New pure helper `history.context_for(flight, stats, route_stats) -> HistoryContext | None`
  (`delta_pct`, `window_days`, `is_lowest`, `since`, `scope` = "data" or "rota").
- `format_azul_alert`, `format_price_alert`, `format_round_trip_alert` take an optional
  context and add one line when present:
  `📉 38% abaixo da média de 60 dias · menor preço desde 20/08`
  `📈 12% acima da média de 60 dias`
  `➖ na média de 60 dias` (within ±3%)
  With only route-level data the line says `da média da rota`. No context → message
  identical to today. Round-trip alerts get no line (totals are not comparable).
- No alert is added, removed or re-keyed. Dedup keys are untouched.

## 5. New panel (`web/`)

- Opening a destination pass fetches and decrypts `history.enc.json` once per session
  (cached in memory), then shows:
  - **Date chart**: inline SVG, daily series of the selected date, median line, historical
    floor, today's point highlighted. Replaces the sparkline inside the open pass; the closed
    pass keeps the sparkline.
  - **Route section**: typical price, floor, cheapest months and weekdays as small bar rows.
  - **When to buy**: lead-time curve, shown only when the route has at least 20 closed dates
    in at least 4 buckets. Otherwise: "Coletando dados — disponível após algumas semanas de
    voos encerrados." No conclusion is invented from thin data.
- Table view gains a "vs. rota" value next to "vs. média".
- History file failing to load degrades to today's behaviour with a quiet notice.
- Chart colours, legend and accessibility follow the existing panel tokens; built with the
  `dataviz` skill guidance at implementation time. No chart library; CSP-safe inline SVG.

## 6. Error handling

| Failure | Behaviour |
|---|---|
| Release restore fails | warn, start empty, cycle continues |
| Release backup fails | warn, job stays green, next cycle retries |
| Migration meets unexpected schema | log error, leave old table, create new one empty |
| `history.json` write fails | log error, `deals.json` still written and deployed |
| Panel cannot load history | passes and table work; chart area shows a notice |
| Empty cycle | existing `EmptyCycleError`; no record, no backup |

## 7. Testing

- `history`: daily-min upsert across three same-day cycles; migration from `price_history`
  (idempotent); `rollup_closed` bucket assignment at the boundaries (7/8, 180/181) and detail
  deletion; `stats` window, `since`, `n`; `route_stats` medians, month/weekday grouping,
  per-date lows merging live and closed data; lead curve built from closed dates only.
- `history_backup`: gzip+encrypt round trip; restore with `gh` mocked (success, missing
  release, corrupt asset); backup never called on empty cycle.
- `encrypt_deals`: v2 payload decrypts and gunzips; v1 payload still decrypts.
- `telegram_bot`: context line for below / above / flat / lowest-since / route-scope / none.
- `cycle`: stats loaded before alerts and before `record`; context passed to senders;
  `history.json` written; ordering test that today's price does not affect today's delta.
- `panel`: new fields present; route-level fields set when the date has under two points.
- Front end: manual browser check of the new pass with a generated fixture (v2 payload),
  including phone width, plus the classic panel still unlocking.

## 8. Rollout

1. Merge; first run migrates the cached database in place and creates the release.
2. Verify in the run log: migration row count, backup upload, snapshot size.
3. Verify the panel unlocks and the chart renders; verify classic still works.
4. Force a cache miss once (bump the cache key prefix) to prove the restore path in CI,
   then keep the new prefix.
