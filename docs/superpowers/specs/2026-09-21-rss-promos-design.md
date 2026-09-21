# Promotions from RSS feeds — design

Date: 2026-09-21
Status: approved in chat, pending spec review
Branch: `feat/rss-promos`

## Problem

The bot only knows what Google Flights shows for the routes and dates it searches. Fare sales,
error fares and miles promotions (transfer bonuses, club offers, discounted miles) are published
by Brazilian travel blogs hours before they show up as prices, and miles promotions never show
up at all. The owner wants those posts filtered for relevance and delivered to Telegram and to
the new panel.

Feeds probed on 2026-09-21:

| Source | URL | Result |
|---|---|---|
| Melhores Destinos | `https://www.melhoresdestinos.com.br/feed` | 200, RSS 2.0, 10 items, title + ~300-char summary, no full content |
| Passageiro de Primeira | `https://passageirodeprimeira.com/feed/` | 200, RSS 2.0, 30 items, title + summary, useful `<category>` values |
| Passagens Imperdíveis | `/feed`, `/rss`, `/rss.xml`, `/blog/feed/` | 404 — the site has no RSS feed |

Feeds almost never state the origin city in the title or summary; the list of cities is inside
the post.

Decisions the owner made in chat:

1. Filter on title + summary only. Posts that cite BH/Confins or a configured destination pass;
   generic posts ("passagens nacionais a partir de…") pass too, labelled "origem não informada".
2. A separate, light workflow runs hourly, with its own dedup state (not `data/cache.db`).
3. Telegram is the fast channel (hourly). The panel section refreshes with the main workflow's
   deploys (three times a day).
4. Two new Telegram topics: "Promoções de passagens" and "Milhas e pontos".
5. Miles posts pass only when they move the balance or the cost of a mile **and** cite a
   Brazilian programme or bank.

## Out of scope

- Passagens Imperdíveis (no feed; would need sitemap/HTML scraping).
- Fetching the full post to find the origin city.
- LLM classification. Revisit only if keyword rules misjudge too often.
- The classic panel.
- Hourly panel refresh (would need a data branch or a second deploy path).
- Extracting prices or dates from the post text.

## 1. Layout

New package `promos/`, four small modules, plus an entry point:

| File | Purpose | Depends on |
|---|---|---|
| `promos/feeds.py` | Download and parse feeds into `FeedItem`s | `httpx`, `lxml` |
| `promos/classify.py` | Pure function: `FeedItem` + config → `Classification \| None` | `config` |
| `promos/state.py` | Load/save `promo_data/promos_state.json`; dedup, pruning, retry and failure counters; write the panel payload | stdlib |
| `promos/notify.py` | Format and send Telegram messages | `telegram_bot.get_bot`, `telegram_bot._md` |
| `promos_main.py` | One cycle; exit code | the four above |

No new dependency: `httpx`, `lxml` and `beautifulsoup4` are already in `requirements.txt`.

```python
@dataclass(frozen=True)
class FeedItem:
    guid: str            # <guid>, falling back to <link>
    title: str
    summary: str         # <description>, HTML stripped, entities decoded
    link: str
    source: str          # display name of the feed, e.g. "Melhores Destinos"
    categories: tuple[str, ...]
    published_at: datetime   # UTC; falls back to fetch time when <pubDate> is missing/invalid

@dataclass(frozen=True)
class Classification:
    kind: str                     # "fare" | "miles"
    destinations: tuple[str, ...] # display labels, e.g. ("Roma", "Milão")
    programs: tuple[str, ...]     # display labels, e.g. ("Livelo", "Smiles")
    from_bh: bool
    origin_unknown: bool          # fare posts only
```

`classify(item)` returns `(Classification | None, reason)`: the reason is reported for rejected
items too, so it travels beside the classification rather than inside it.

## 2. One cycle (`promos_main.py`)

1. `state.load()` — missing or unreadable file yields an empty state and a warning; never raises.
2. `feeds.fetch_all(config.PROMO_FEEDS)` — per feed: 20 s timeout, browser User-Agent, follow
   redirects. A failing feed is logged, its failure counter is incremented, and the others go
   on. A feed that succeeds resets its counter. Items without title or link are skipped.
3. For each item whose guid is not in the seen set: `classify`. A rejected item is marked seen
   immediately so it is not reclassified every hour.
4. Accepted items are added to the state's promo list (that list feeds the panel), then sent
   oldest-first through `notify`, at most `PROMO_MAX_MESSAGES_PER_CYCLE = 10` per cycle. Items
   beyond the cap are marked seen and stay panel-only; the log says how many.
5. `state.save()` — seen guids pruned after 30 days, promos after 14 days. Also writes
   `promo_data/promos.json`, the panel payload (section 6).
6. Exit 0, unless **every** feed failed: exit 1.

**Seeding.** When the state is empty (first run, corrupt file, evicted cache), every item is
recorded but only those published in the last `PROMO_SEED_MAX_AGE_HOURS = 6` are sent. Otherwise
the first run would post ~40 old items.

**Send failures.** If Telegram rejects a message the guid is not marked seen and a per-guid
attempt counter is incremented; after 3 attempts it is marked seen with an error log. The item
is in the panel list regardless. On `RetryAfter` (429) `notify` waits the time Telegram asks for,
capped at 30 s, and retries once (`telegram_bot` has no flood handling to reuse).

**Topics not configured.** While `PROMO_TOPIC_FARES` / `PROMO_TOPIC_MILES` are `None`, items
of that kind are classified, recorded and marked seen, nothing is sent, and the log says so.
This lets the feature merge and the panel be verified before the owner creates the topics.
(`None` must not fall back to General here, unlike `Group.topic_id`.)

**Health.** When a feed's failure counter reaches 6 consecutive cycles, one
`telegram_bot.send_health_alert` is sent (a flag in the state prevents repeats until the feed
recovers).

## 3. Classification rules (`promos/classify.py`)

Text = title + " " + summary, lowercased, accents stripped, matched on word boundaries
("cnf" must not match inside another word; "roma" must not match "aroma"). Config terms are
normalised the same way at match time, so they are written naturally in `config.py`; the miles
signals are regular expressions and are written already lowercase and unaccented.

**Step 1 — miles.** Accept as `miles` when both hold:
- a promotion signal from `PROMO_MILES_SIGNALS`: transfer bonus ("bônus" with "transferência" /
  "transferir", "transferência bonificada"), buying points/miles ("compra de pontos",
  "compra de milhas", "milheiro"), "clube", "resgate", "pontos por real", "ganhe|acumule … pontos|milhas";
- a Brazilian programme or bank from `PROMO_MILES_PROGRAMS`: Azul Fidelidade / TudoAzul, Smiles,
  Latam Pass, Livelo, Esfera, Iupp, Átomos, Itaú, Bradesco, Santander, Banco do Brasil, Caixa,
  C6, Inter, Nubank, XP, BTG.

Hotel programmes and foreign programmes alone do not qualify. "Livelo com 100% de bônus para o
Flying Blue" passes because of Livelo. `programs` lists every programme matched. If the text
also cites a configured destination, `destinations` is filled too.

**Step 2 — fare.** Otherwise, require a fare word ("passagem/passagens", "voo/voos", "tarifa",
"ida e volta", "trecho") **and** an offer signal: an `R$` price or an offer word ("promoção",
"oferta", "desconto", "barato/baratas", "tarifa erro"). The fare word is always required, or
"hotéis a partir de R$ 300" would pass; "a partir de" alone is not an offer signal, or the news
"voos … a partir de 2027" would pass. Then, in order:

1. Cites BH / Belo Horizonte / Confins / CNF / Minas Gerais → accept, `from_bh=True`.
2. Cites a configured destination → accept with `destinations`. Destination terms are the city
   names in `config.AIRPORTS` plus `PROMO_DESTINATION_ALIASES` (e.g. "Itália", "Portugal",
   "Espanha", "França", "Europa", "Patagônia", "Foz", "Floripa", "Rio").
3. Generic (`PROMO_GENERIC_TERMS`: "nacionais", "internacionais", "várias cidades",
   "todo o brasil", …) → accept, `origin_unknown=True`, even when other cities are listed.
4. Only places outside the config → reject. Recognising "a place outside the config" needs a
   list: `PROMO_OTHER_PLACES`, common sale destinations and origins that are not configured
   (Miami, Orlando, Nova York, Buenos Aires, Cancún, Londres, Salvador, Recife, Fortaleza,
   Brasília, …). Place names are matched longest first, so "Porto Seguro" is never "Porto".
5. No place recognised at all → accept, `origin_unknown=True`. A post citing a place missing
   from both lists lands here and passes as origin unknown — the tolerant side, consistent with decision 1. The list grows from the
   classification log.

Rules 1 and 2 can both apply; `origin_unknown` is set whenever `from_bh` is false.

An item matching both steps is `miles`. One item, one message.

The reason names the rule and the matched term (`"fare:destination:Roma"`, `"miles:Livelo"`,
`"rejected:no-offer-signal"`); every decision is logged at INFO so a wrong verdict can be traced
to a word.

**Calibration.** The two real feeds of 2026-09-21 are saved as fixtures. Before any push the
owner gets a table of every fixture item with its verdict.

## 4. Telegram messages (`promos/notify.py`)

Fare, to `PROMO_TOPIC_FARES`:

```
✈️ *<title>*
📍 <🟢 saindo de BH | destinations> · origem não informada   (last part only when origin_unknown)
📰 <source> · <HH:MM Brasília>
<summary, cut at ~200 chars on a word boundary, with …>
🔗 [Ver a promoção](<link>)
```

Miles, to `PROMO_TOPIC_MILES`: same, opening with 💳 and with `🏷️ <programs>` instead of the 📍
line (plus the destinations when present).

All feed text goes through `telegram_bot._md()`. Link previews are disabled. Markdown mode is
the one `telegram_bot` already uses.

## 5. Workflows

**New `.github/workflows/promos.yml`**: cron `17 * * * *`, `workflow_dispatch`, concurrency group
`promos` (no cancel-in-progress), `timeout-minutes: 5`, `permissions: contents: read`. Steps:
checkout, setup-python 3.11, `pip install -r requirements.txt`, `actions/cache@v4` on
`promo_data/` (key `promos-state-${{ github.run_id }}`, restore-key `promos-state-`),
`python promos_main.py` with `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHANNEL_ID`.

**`azul-alert.yml`**: before "Encrypt deals and history", an `actions/cache/restore@v4` step for
`promo_data/` with the same restore-key (read-only, so the two workflows never race on a save),
`continue-on-error: true`. "Assemble site" copies `promos.enc.json` when it exists.

`promo_data/` is added to `.gitignore`.

## 6. Panel payload and encryption

`promo_data/promos.json`:

```json
{ "gerado_em": "2026-09-21T14:17:03Z",
  "promos": [ { "tipo": "passagem|milhas", "titulo": "", "resumo": "", "link": "", "fonte": "",
                "publicado_em": "", "destinos": [], "programas": [],
                "origem_bh": false, "origem_nao_informada": false } ] }
```

Newest first, last 14 days. Seen guids and counters stay in `promos_state.json` and are never
published. `scripts/encrypt_deals.py` encrypts `promo_data/promos.json` to `promos.enc.json`
(payload v2, same password) when the file exists; absence is not an error. The repo is public:
nothing leaves the runner unencrypted.

## 7. New panel (`web/index.html`, `web/app.js`, `web/style.css`)

A "Promoções" section between the "Em destaque agora" board and the counters. `app.js` loads
`promos.enc.json` with `PanelCrypto.load` in parallel with the deals; a 404 or any failure hides
the section and the rest of the panel is unaffected.

Compact rows in the departures-board style: relative time ("há 3 h", "ontem"), kind badge,
title as a link (`target="_blank" rel="noopener noreferrer"`), destination/programme tags,
source. Segmented buttons Todas · Passagens · Milhas. Eight rows, then "ver mais". `origem_bh`
rows get the accent colour. Third-party text is set with `textContent`, never `innerHTML`, and
links are only rendered when they start with `https://`.

Verified per the project routine: encrypted fixture in `_site/`, `python -m http.server`,
browser preview at desktop width and 375 px, password `teste123`.

## 8. Tests (pytest, no network)

- `tests/test_promo_feeds.py` — both real fixtures parse; CDATA and HTML entities; missing guid
  falls back to link; missing pubDate; invalid XML; timeout via `httpx.MockTransport`; one feed
  failing does not stop the other.
- `tests/test_promo_classify.py` — table of real cases: Italy sale → fare with Roma, Milão;
  "nacionais a partir de R$ 336" → fare, origin unknown; British Airways news → rejected;
  Oktoberfest → rejected; IHG → rejected; Livelo bonus → miles; Miami-only → rejected; "cnf"
  inside a word does not match; accented and unaccented spellings; both-kinds item → miles.
- `tests/test_promo_state.py` — dedup; pruning (30 d / 14 d); seeding; corrupt file; attempt
  counter; failure counter and health flag; payload excludes guids.
- `tests/test_promo_notify.py` — Markdown escaping of `_ * [ ]` in titles; topic routing; cap of
  10; `None` topic sends nothing; summary truncation.
- `tests/test_promos_main.py` — full cycle with mocks; one feed down; all feeds down → exit 1;
  health alert fires once at 6.
- `tests/test_encrypt_deals.py` — `promos.json` present and absent.

`timeout 100 python -m pytest -q` stays green (291 today).

## 9. Activation

1. Merge to master, owner authorises the push.
2. Manual `promos.yml` run with both topics `None`: read the classification log.
3. Owner creates the two topics; ids found with `scripts/list_topics.py`; set in `config.py`.
4. Second manual run: at least one real promotion reaches each topic (miles may take a day).
5. After the next main-workflow deploy: `promos.enc.json` returns 200 and the panel section is
   checked in the browser.
