# RSS Promotions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Read two travel-blog RSS feeds every hour, keep the posts that matter to a traveller based in Belo Horizonte (fare sales and Brazilian miles promotions), post them to two Telegram forum topics and show them in a section of the new panel.

**Architecture:** A new `promos/` package with four small modules (`feeds`, `classify`, `state`, `notify`) driven by `promos_main.py`, run hourly by a new light workflow with its own `actions/cache` state (`promo_data/`). The main workflow only *reads* that state, encrypts `promo_data/promos.json` into `promos.enc.json` and ships it with the site; the new panel decrypts it with the existing `PanelCrypto`.

**Tech Stack:** Python 3.11, `httpx`, `lxml`, `beautifulsoup4`, `python-telegram-bot` 21.3 (all already in `requirements.txt` — add nothing), pytest + pytest-asyncio (`asyncio_mode = auto`) + pytest-mock, vanilla JS/CSS panel.

**Spec:** `docs/superpowers/specs/2026-09-21-rss-promos-design.md`

## Global Constraints

- No new dependency in `requirements.txt`. `primp` stays pinned at 2.0.0.
- Code, comments, commit messages and config names in English. Every user-facing string (Telegram text, panel text, log lines) in Portuguese, matching the existing code.
- Run tests only as `timeout 100 python -m pytest -q` (a failing async test can leave an aiosqlite thread alive and hang the interpreter). The suite has 291 tests today and must stay green.
- **Git Bash heredoc trap on this PC:** inside `python - <<'EOF'` a double backslash collapses and an escaped `\n` becomes a real line break. Create and change files with the Write/Edit tools only; never generate code through a heredoc.
- The repository is **public**: nothing leaves the runner unencrypted. `promo_data/` and `promos.enc.json` are git-ignored.
- Never `git push`. Commit on branch `feat/rss-promos` only. End every commit message with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Do not touch the classic panel (`web/classic/`).
- All text that came from a feed goes through `telegram_bot._md()` before entering a Telegram message, and through `textContent` (never `innerHTML`) in the panel.
- A topic id of `None` means "do not send" for promotions. It must **not** fall back to the General thread.
- Exact values: `PROMO_MAX_MESSAGES_PER_CYCLE = 10`, `PROMO_SEED_MAX_AGE_HOURS = 6`, seen guids pruned after 30 days, promos after 14 days, 3 send attempts, health alert at 6 consecutive feed failures, feed timeout 20 s, workflow cron `17 * * * *`, `timeout-minutes: 5`.

## File Structure

| File | Responsibility |
|---|---|
| `promos/__init__.py` | empty package marker |
| `promos/feeds.py` | `FeedItem`, `parse_feed`, `fetch_all` — network + XML only |
| `promos/classify.py` | `Classification`, `normalize`, `classify` — pure rules |
| `promos/state.py` | `PromoState`, `load`, `save` — dedup, pruning, counters, panel payload |
| `promos/notify.py` | `format_promo`, `send_promo` — Telegram only |
| `promos_main.py` | `run_cycle`, exit code, logging |
| `scripts/promo_verdicts.py` | calibration table: every live feed item with its verdict |
| `config.py` | `PROMO_*` settings and word lists |
| `scripts/encrypt_deals.py` | also encrypts `promo_data/promos.json` |
| `.github/workflows/promos.yml` | hourly workflow |
| `.github/workflows/azul-alert.yml` | read-only restore of `promo_data/`, copy `promos.enc.json` |
| `web/index.html`, `web/app.js`, `web/style.css` | "Promoções" section |
| `tests/fixtures/promo_feed_sample.xml` | hand-written deterministic feed |
| `tests/test_promo_*.py`, `tests/test_promos_main.py` | tests |

---

### Task 1: Feed download and parsing

**Files:**
- Create: `promos/__init__.py` (empty), `promos/feeds.py`
- Create: `tests/fixtures/promo_feed_sample.xml`
- Test: `tests/test_promo_feeds.py`
- Modify: `config.py` (append at the end), `.gitignore`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces:
  - `promos.feeds.FeedItem` — frozen dataclass: `guid: str`, `title: str`, `summary: str`, `link: str`, `source: str`, `categories: tuple[str, ...]`, `published_at: datetime` (UTC, tz-aware).
  - `promos.feeds.FeedError(Exception)`.
  - `promos.feeds.parse_feed(xml: bytes, source: str, now: datetime) -> list[FeedItem]` — raises `FeedError` when the document has no `<channel><item>`.
  - `async promos.feeds.fetch_all(feeds: list[tuple[str, str]], now: datetime | None = None, transport: httpx.AsyncBaseTransport | None = None) -> tuple[list[FeedItem], dict[str, bool]]` — second value maps each source name to whether it succeeded. Never raises.
  - `config.PROMO_FEEDS: list[tuple[str, str]]` — `(source name, url)`.

- [ ] **Step 1: Write the fixture**

Create `tests/fixtures/promo_feed_sample.xml`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">
<channel>
  <title>Blog de Teste</title>
  <link>https://example.com</link>
  <item>
    <title>Itália nas férias! Voos para Roma ou Milão a partir de R$ 4.270 ida e volta</title>
    <link>https://example.com/italia.html</link>
    <pubDate>Fri, 18 Sep 2026 20:21:01 +0000</pubDate>
    <category><![CDATA[Promoções]]></category>
    <category><![CDATA[Passagens Aéreas]]></category>
    <guid isPermaLink="false">https://example.com/?p=1</guid>
    <description><![CDATA[<p>A <b>Ita Airways</b> tem tarifas   para dezembro&#8230;</p>]]></description>
  </item>
  <item>
    <title>Sem guid: Livelo com 100% de bônus na transferência para a Smiles</title>
    <link>https://example.com/livelo.html</link>
    <pubDate>Sat, 19 Sep 2026 09:00:00 -0300</pubDate>
    <description><![CDATA[Transfira seus pontos até domingo.]]></description>
  </item>
  <item>
    <title>Sem data</title>
    <link>https://example.com/sem-data.html</link>
    <guid>https://example.com/?p=3</guid>
    <pubDate>isto não é uma data</pubDate>
    <description></description>
  </item>
  <item>
    <title></title>
    <link>https://example.com/sem-titulo.html</link>
    <guid>https://example.com/?p=4</guid>
  </item>
  <item>
    <title>Sem link</title>
    <guid>https://example.com/?p=5</guid>
  </item>
</channel>
</rss>
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_promo_feeds.py`:

```python
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from promos.feeds import FeedError, FeedItem, fetch_all, parse_feed

SAMPLE = (Path(__file__).parent / "fixtures" / "promo_feed_sample.xml").read_bytes()
NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)


def test_parses_title_link_guid_categories_and_utc_date():
    items = parse_feed(SAMPLE, "Blog de Teste", NOW)
    first = items[0]
    assert isinstance(first, FeedItem)
    assert first.title.startswith("Itália nas férias!")
    assert first.link == "https://example.com/italia.html"
    assert first.guid == "https://example.com/?p=1"
    assert first.source == "Blog de Teste"
    assert first.categories == ("Promoções", "Passagens Aéreas")
    assert first.published_at == datetime(2026, 9, 18, 20, 21, 1, tzinfo=timezone.utc)


def test_summary_has_html_stripped_entities_decoded_and_whitespace_collapsed():
    first = parse_feed(SAMPLE, "Blog de Teste", NOW)[0]
    assert first.summary == "A Ita Airways tem tarifas para dezembro…"


def test_missing_guid_falls_back_to_the_link_and_offsets_become_utc():
    second = parse_feed(SAMPLE, "Blog de Teste", NOW)[1]
    assert second.guid == "https://example.com/livelo.html"
    assert second.published_at == datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)


def test_invalid_pubdate_falls_back_to_now():
    third = parse_feed(SAMPLE, "Blog de Teste", NOW)[2]
    assert third.published_at == NOW
    assert third.summary == ""


def test_items_without_title_or_link_are_skipped():
    assert len(parse_feed(SAMPLE, "Blog de Teste", NOW)) == 3


@pytest.mark.parametrize("body", [b"", b"this is not xml", b"<html><body>404</body></html>",
                                  b"<rss><channel><title>vazio</title></channel></rss>"])
def test_documents_without_items_raise_feed_error(body):
    with pytest.raises(FeedError):
        parse_feed(body, "Blog de Teste", NOW)


async def test_fetch_all_keeps_going_when_one_feed_fails():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "bom.example":
            return httpx.Response(200, content=SAMPLE)
        return httpx.Response(404, content=b"<html>nada</html>")

    items, ok = await fetch_all(
        [("Quebrado", "https://ruim.example/feed"), ("Bom", "https://bom.example/feed")],
        now=NOW, transport=httpx.MockTransport(handler))
    assert ok == {"Quebrado": False, "Bom": True}
    assert [i.source for i in items] == ["Bom", "Bom", "Bom"]


async def test_fetch_all_survives_a_timeout_and_sends_a_browser_user_agent():
    seen_agents = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_agents.append(request.headers["user-agent"])
        raise httpx.ReadTimeout("lento demais", request=request)

    items, ok = await fetch_all([("Lento", "https://lento.example/feed")],
                                now=NOW, transport=httpx.MockTransport(handler))
    assert items == [] and ok == {"Lento": False}
    assert seen_agents[0].startswith("Mozilla/5.0")
```

- [ ] **Step 3: Run the tests and watch them fail**

Run: `timeout 100 python -m pytest tests/test_promo_feeds.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'promos'`.

- [ ] **Step 4: Implement**

Create the empty file `promos/__init__.py`.

Create `promos/feeds.py`:

```python
"""Download and parse the promotion RSS feeds.

Network and XML only: what an item means is classify.py's job. A feed that fails is reported
in the result and never stops the others; fetch_all never raises.
"""
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx
from bs4 import BeautifulSoup
from lxml import etree

logger = logging.getLogger(__name__)

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
TIMEOUT_SECONDS = 20


class FeedError(Exception):
    """The document is not a feed with items."""


@dataclass(frozen=True)
class FeedItem:
    guid: str
    title: str
    summary: str
    link: str
    source: str
    categories: tuple[str, ...]
    published_at: datetime   # UTC


def _clean(html: str | None) -> str:
    """Feed text is HTML inside XML: strip tags, decode entities, collapse whitespace."""
    text = BeautifulSoup(html or "", "lxml").get_text(" ")
    return re.sub(r"\s+", " ", text).strip()


def _published(text: str | None, now: datetime) -> datetime:
    try:
        parsed = parsedate_to_datetime(text or "")
    except (TypeError, ValueError):
        return now
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_feed(xml: bytes, source: str, now: datetime) -> list[FeedItem]:
    # recover=True: WordPress feeds carry the odd stray character; a broken document still
    # ends up with no <item> and is rejected below.
    parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=True)
    try:
        root = etree.fromstring(xml, parser)
    except (etree.XMLSyntaxError, ValueError) as e:
        raise FeedError(f"unparseable: {e}") from e
    nodes = root.findall("./channel/item") if root is not None else []
    if not nodes:
        raise FeedError("no <item> in the document")

    items = []
    for node in nodes:
        title = _clean(node.findtext("title"))
        link = (node.findtext("link") or "").strip()
        if not title or not link:
            continue
        items.append(FeedItem(
            guid=(node.findtext("guid") or "").strip() or link,
            title=title,
            summary=_clean(node.findtext("description")),
            link=link,
            source=source,
            categories=tuple(c for c in (_clean(n.text) for n in node.findall("category")) if c),
            published_at=_published(node.findtext("pubDate"), now),
        ))
    return items


async def fetch_all(feeds: list[tuple[str, str]], now: datetime | None = None,
                    transport: httpx.AsyncBaseTransport | None = None,
                    ) -> tuple[list[FeedItem], dict[str, bool]]:
    """Every item of every feed that answered, plus which feeds did."""
    now = now or datetime.now(timezone.utc)
    items: list[FeedItem] = []
    ok: dict[str, bool] = {}
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, follow_redirects=True,
                                 headers={"User-Agent": USER_AGENT}, transport=transport) as client:
        for source, url in feeds:
            try:
                response = await client.get(url)
                response.raise_for_status()
                parsed = parse_feed(response.content, source, now)
            except (httpx.HTTPError, FeedError) as e:
                logger.warning(f"feed {source} falhou: {e!r}")
                ok[source] = False
                continue
            ok[source] = True
            items.extend(parsed)
    return items, ok
```

Append to the end of `config.py`:

```python

# --- Promotions from RSS feeds (promos/, promos_main.py) ---
PROMO_FEEDS: list[tuple[str, str]] = [
    ("Melhores Destinos", "https://www.melhoresdestinos.com.br/feed"),
    ("Passageiro de Primeira", "https://passageirodeprimeira.com/feed/"),
]
```

Append to `.gitignore`:

```
promo_data/
promos.enc.json
```

- [ ] **Step 5: Run the tests and watch them pass**

Run: `timeout 100 python -m pytest tests/test_promo_feeds.py -q`
Expected: all pass (11 with the parametrised cases).

- [ ] **Step 6: Commit**

```bash
git add promos/__init__.py promos/feeds.py tests/fixtures/promo_feed_sample.xml tests/test_promo_feeds.py config.py .gitignore
git commit -m "feat(promos): download and parse the promotion feeds

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Classification rules

**Files:**
- Create: `promos/classify.py`
- Modify: `config.py` (append after `PROMO_FEEDS`)
- Test: `tests/test_promo_classify.py`

**Interfaces:**
- Consumes: `promos.feeds.FeedItem` (fields above); `config.AIRPORTS: dict[str, Airport]` where `Airport` has `.cidade`; `config.AZUL_HUB = "CNF"`.
- Produces:
  - `promos.classify.Classification` — frozen dataclass: `kind: str` (`"fare"` or `"miles"`), `destinations: tuple[str, ...]`, `programs: tuple[str, ...]`, `from_bh: bool`, `origin_unknown: bool`.
  - `promos.classify.normalize(text: str) -> str` — lowercase, accents stripped.
  - `promos.classify.classify(item: FeedItem) -> tuple[Classification | None, str]` — the second value is always the reason (`"fare:home"`, `"fare:destination:Roma"`, `"fare:generic:nacionais"`, `"fare:no-place"`, `"miles:Livelo"`, `"rejected:no-fare-word"`, `"rejected:no-offer-signal"`, `"rejected:other-place:Miami"`).

**Rules (from the spec, section 3).** Text = `title + " " + summary`, normalised, matched on word boundaries.

1. *Miles* when a regex from `PROMO_MILES_SIGNALS` matches **and** a term from `PROMO_MILES_PROGRAMS` is cited. Destinations are filled when cited.
2. Otherwise *fare* needs a fare word (`PROMO_FARE_WORDS`) **and** an offer signal: an `R$` price or a word from `PROMO_OFFER_WORDS`. ("a partir de" alone is not an offer signal: "voos a partir de 2027" is news.)
3. Place, in order: home term → `from_bh`; configured destination → `destinations`; either one accepts. Else a generic term accepts with `origin_unknown`. Else a place from `PROMO_OTHER_PLACES` rejects. Else (no place at all) accept with `origin_unknown`.
4. Places are matched longest-first and each match is blanked out, so "Porto Alegre" and "Porto Seguro" never count as "Porto", nor "Rio Branco" as "Rio".

- [ ] **Step 1: Write the failing tests**

Create `tests/test_promo_classify.py`:

```python
from datetime import datetime, timezone

import pytest

from promos.classify import Classification, classify, normalize
from promos.feeds import FeedItem


def item(title: str, summary: str = "") -> FeedItem:
    return FeedItem(guid=title, title=title, summary=summary, link="https://example.com/x",
                    source="Teste", categories=(), published_at=datetime(2026, 9, 21, tzinfo=timezone.utc))


def test_normalize_strips_accents_and_lowercases():
    assert normalize("Milão, SÃO LUÍS e Florianópolis") == "milao, sao luis e florianopolis"


def test_italy_sale_is_a_fare_with_both_cities_in_text_order():
    c, reason = classify(item("Itália nas férias! Voos para Roma ou Milão a partir de R$ 4.270 ida e volta"))
    assert c == Classification(kind="fare", destinations=("Itália", "Roma", "Milão"), programs=(),
                               from_bh=False, origin_unknown=True)
    assert reason == "fare:destination:Itália"


def test_generic_national_sale_passes_with_origin_unknown():
    c, reason = classify(item("Ofertas do fim de semana! Passagens nacionais a partir de R$ 336 "
                              "ida e volta com Azul, Gol e Latam"))
    assert c is not None and c.kind == "fare"
    assert c.destinations == () and c.origin_unknown and not c.from_bh
    assert reason == "fare:generic:nacionais"


def test_generic_sale_listing_other_cities_still_passes():
    c, _ = classify(item("Passagens nacionais em promoção", "Trechos para Salvador, Recife e Fortaleza."))
    assert c is not None and c.origin_unknown


def test_home_city_sets_from_bh():
    c, reason = classify(item("Voos saindo de Belo Horizonte para Miami a partir de R$ 2.100"))
    assert c is not None and c.from_bh and not c.origin_unknown
    assert reason == "fare:home"


@pytest.mark.parametrize("home", ["BH", "Confins", "CNF", "belo horizonte"])
def test_every_home_term_counts(home):
    c, _ = classify(item(f"Passagens em promoção saindo de {home}"))
    assert c is not None and c.from_bh


def test_news_about_new_flights_is_rejected_even_with_a_configured_city():
    c, reason = classify(item(
        "Acabou a escala! British Airways terá voos exclusivos entre Londres e Rio de Janeiro a partir de 2027",
        "A British Airways anunciou mudanças e passará a oferecer um voo diário sem escalas."))
    assert c is None and reason == "rejected:no-offer-signal"


def test_non_flight_posts_are_rejected():
    c, reason = classify(item("Começa hoje! Oktoberfest São Paulo volta ao Ibirapuera com muito chope"))
    assert c is None and reason == "rejected:no-fare-word"


def test_hotel_price_without_a_fare_word_is_rejected():
    c, reason = classify(item("Hotéis em Roma com diárias a partir de R$ 300"))
    assert c is None and reason == "rejected:no-fare-word"


def test_sale_to_a_place_outside_the_config_is_rejected():
    c, reason = classify(item("Voos para Miami a partir de R$ 2.000 ida e volta"))
    assert c is None and reason == "rejected:other-place:Miami"


def test_sale_with_no_place_at_all_passes_as_origin_unknown():
    c, reason = classify(item("Tarifa erro? Passagens com 70% de desconto na Latam"))
    assert c is not None and c.origin_unknown and reason == "fare:no-place"


def test_porto_seguro_is_not_porto_and_rio_branco_is_not_rio():
    c, reason = classify(item("Voos para Porto Seguro e Rio Branco a partir de R$ 400"))
    assert c is None and reason == "rejected:other-place:Porto Seguro"


def test_porto_alegre_is_its_own_destination():
    c, _ = classify(item("Passagens para Porto Alegre a partir de R$ 250"))
    assert c is not None and c.destinations == ("Porto Alegre",)


def test_words_only_match_whole():
    # "aroma" contains "roma"; "bhutan" starts with "bh"
    c, reason = classify(item("Passagens em promoção para o Bhutan, terra do aroma de incenso"))
    assert c is not None and c.destinations == () and not c.from_bh


def test_unaccented_spelling_matches_too():
    c, _ = classify(item("Voos para Milao e Sao Luis a partir de R$ 500"))
    assert c is not None and c.destinations == ("Milão", "São Luís")


def test_transfer_bonus_is_miles_with_every_programme_in_text_order():
    c, reason = classify(item("Livelo oferece até 100% de bônus na transferência de pontos para a Smiles"))
    assert c == Classification(kind="miles", destinations=(), programs=("Livelo", "Smiles"),
                               from_bh=False, origin_unknown=False)
    assert reason == "miles:Livelo"


@pytest.mark.parametrize("title", [
    "Smiles vende milhas com até 80% de desconto na compra de milhas",
    "Clube Latam Pass com 3 meses grátis",
    "Azul Fidelidade: resgate de passagens a partir de 3 mil pontos",
    "Ganhe 10 pontos por real no Esfera comprando na Amazon",
    "Acumule até 12 pontos Livelo por real",
    "Milheiro Smiles a R$ 16 na promoção de hoje",
    "TudoAzul: transferência bonificada do Itaú",
])
def test_miles_signals(title):
    c, _ = classify(item(title))
    assert c is not None and c.kind == "miles"


def test_foreign_or_hotel_programmes_alone_are_not_miles():
    c, _ = classify(item("IHG One Rewards oferece até o triplo de pontos em estadias"))
    assert c is None
    c, _ = classify(item("Flying Blue tem bônus na compra de milhas"))
    assert c is None


def test_a_brazilian_programme_carries_a_foreign_one():
    c, _ = classify(item("Livelo com 100% de bônus na transferência para o Flying Blue"))
    assert c is not None and c.kind == "miles" and c.programs == ("Livelo",)


def test_post_matching_both_kinds_is_miles_and_keeps_the_destination():
    c, _ = classify(item("Resgate Smiles: voos para Lisboa por 35 mil milhas o trecho, em promoção"))
    assert c is not None and c.kind == "miles" and c.destinations == ("Lisboa",)


def test_news_about_a_programme_without_a_promotion_signal_is_not_miles():
    c, _ = classify(item("Smiles anuncia novo diretor de marketing"))
    assert c is None


def test_the_summary_counts_too():
    c, _ = classify(item("Promoção relâmpago da Gol", "Passagens saindo de Confins a partir de R$ 199."))
    assert c is not None and c.from_bh
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `timeout 100 python -m pytest tests/test_promo_classify.py -q`
Expected: `ModuleNotFoundError: No module named 'promos.classify'`.

- [ ] **Step 3: Add the word lists to `config.py`**

Append after `PROMO_FEEDS`:

```python
PROMO_TOPIC_FARES: int | None = None    # forum topic "Promoções de passagens"; None = send nothing
PROMO_TOPIC_MILES: int | None = None    # forum topic "Milhas e pontos"; None = send nothing
PROMO_MAX_MESSAGES_PER_CYCLE: int = 10
PROMO_SEED_MAX_AGE_HOURS: int = 6       # with no state yet, older posts are recorded, not sent

# Every term below is matched on whole words after lowercasing and stripping accents, so write
# them naturally. The signals are regular expressions run on that normalised text, so they are
# written already lowercase and unaccented.
PROMO_HOME_TERMS: tuple[str, ...] = ("BH", "Belo Horizonte", "Confins", "CNF", "Minas Gerais")

# Extra names for configured destinations: term -> label shown to the owner. The city names of
# AIRPORTS (hub excluded) are destination terms already.
PROMO_DESTINATION_ALIASES: dict[str, str] = {
    "Itália": "Itália", "Portugal": "Portugal", "Espanha": "Espanha", "França": "França",
    "Europa": "Europa", "Patagônia": "Patagônia", "Madrid": "Madri",
    "Foz": "Foz do Iguaçu", "Floripa": "Florianópolis", "Rio": "Rio de Janeiro",
}

# A sale that names one of these words is about many cities: it passes as "origin unknown".
PROMO_GENERIC_TERMS: tuple[str, ...] = (
    "nacionais", "internacionais", "várias cidades", "diversas cidades", "vários destinos",
    "diversos destinos", "todo o Brasil", "qualquer destino",
)

# Places that are not configured. A sale naming only these is dropped; a place missing from
# both lists passes as "origin unknown". Grow this list from the classification log.
# Left out on purpose: "Natal" and "Vitória" (a Christmas sale is not a sale to Natal).
# Longer names shadow shorter ones, which is why "Porto Seguro" and "Rio Branco" are here.
PROMO_OTHER_PLACES: tuple[str, ...] = (
    "Miami", "Orlando", "Nova York", "Nova Iorque", "Los Angeles", "Las Vegas", "Cancún",
    "Punta Cana", "Buenos Aires", "Montevidéu", "Lima", "Bogotá", "Cartagena", "Londres",
    "Amsterdã", "Frankfurt", "Zurique", "Dubai", "Tóquio", "Estados Unidos", "Caribe",
    "Salvador", "Recife", "Fortaleza", "Maceió", "João Pessoa", "Aracaju", "Brasília",
    "Goiânia", "Cuiabá", "Campo Grande", "Manaus", "Belém", "Curitiba", "Campinas",
    "Guarulhos", "Porto Seguro", "Porto de Galinhas", "Porto Velho", "Rio Branco",
    "Rio Grande do Norte", "Rio Grande do Sul", "São José do Rio Preto", "Fernando de Noronha",
    "Jericoacoara", "Ilhéus",
)

PROMO_FARE_WORDS: tuple[str, ...] = (
    "passagem", "passagens", "voo", "voos", "tarifa", "tarifas", "ida e volta", "trecho", "trechos",
)
PROMO_OFFER_WORDS: tuple[str, ...] = (
    "promoção", "promoções", "oferta", "ofertas", "desconto", "descontos", "barato", "barata",
    "baratos", "baratas", "tarifa erro",
)

PROMO_MILES_SIGNALS: tuple[str, ...] = (
    r"bonus\w*\b.{0,60}\btransfer", r"\btransfer\w*\b.{0,60}\bbonus", r"transferencia bonificada",
    r"\bcompra de (pontos|milhas)\b", r"\bmilheiro\b", r"\bclube\b", r"\bresgate\w*\b",
    r"\bpontos por real\b", r"\b(ganhe|acumule)\b.{0,40}\b(pontos|milhas)\b",
)
# term -> label. Brazilian programmes and banks only: a hotel or foreign programme alone is out.
PROMO_MILES_PROGRAMS: dict[str, str] = {
    "Azul Fidelidade": "Azul Fidelidade", "TudoAzul": "Azul Fidelidade", "Tudo Azul": "Azul Fidelidade",
    "Smiles": "Smiles", "Latam Pass": "Latam Pass", "Livelo": "Livelo", "Esfera": "Esfera",
    "Iupp": "Iupp", "Átomos": "Átomos", "Itaú": "Itaú", "Bradesco": "Bradesco",
    "Santander": "Santander", "Banco do Brasil": "Banco do Brasil", "Caixa": "Caixa", "C6": "C6",
    "Banco Inter": "Inter", "Inter Loop": "Inter", "Nubank": "Nubank", "XP": "XP", "BTG": "BTG",
}
```

- [ ] **Step 4: Implement `promos/classify.py`**

```python
"""Decide whether a feed item matters to the owner. Pure: no network, no clock, no state.

Feeds carry a title and a ~300-character summary and almost never name the origin city, so the
rules are tolerant on purpose (the owner's choice): anything that may be a sale from Belo
Horizonte passes, labelled with what is actually known.
"""
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

import config
from promos.feeds import FeedItem

_PRICE = re.compile(r"r\$\s?\d")


@dataclass(frozen=True)
class Classification:
    kind: str                       # "fare" | "miles"
    destinations: tuple[str, ...]   # display labels, in the order the text cites them
    programs: tuple[str, ...]       # display labels, in the order the text cites them
    from_bh: bool
    origin_unknown: bool            # fare posts only


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


@lru_cache(maxsize=None)
def _word(term: str) -> re.Pattern:
    return re.compile(r"(?<!\w)" + re.escape(normalize(term)) + r"(?!\w)")


def _first(terms, text: str) -> str | None:
    return next((t for t in terms if _word(t).search(text)), None)


def _labels_in_order(table: dict[str, str], text: str) -> tuple[str, ...]:
    """Labels of the terms present, ordered by where each first shows up, without repeats."""
    hits = []
    for term, label in table.items():
        found = _word(term).search(text)
        if found:
            hits.append((found.start(), label))
    ordered = []
    for _pos, label in sorted(hits):
        if label not in ordered:
            ordered.append(label)
    return tuple(ordered)


def _places(text: str) -> dict[str, tuple[str, ...]]:
    """Home, destination and other places cited. Longest names are matched first and blanked
    out, so "Porto Alegre" and "Porto Seguro" are never also counted as "Porto"."""
    table: list[tuple[str, str, str]] = [(t, "home", t) for t in config.PROMO_HOME_TERMS]
    table += [(a.cidade, "dest", a.cidade) for code, a in config.AIRPORTS.items() if code != config.AZUL_HUB]
    table += [(t, "dest", label) for t, label in config.PROMO_DESTINATION_ALIASES.items()]
    table += [(t, "other", t) for t in config.PROMO_OTHER_PLACES]
    table.sort(key=lambda row: len(normalize(row[0])), reverse=True)

    hits: dict[str, list[tuple[int, str]]] = {"home": [], "dest": [], "other": []}
    for term, kind, label in table:
        pattern = _word(term)
        found = pattern.search(text)
        if not found:
            continue
        hits[kind].append((found.start(), label))
        text = pattern.sub(lambda m: " " * len(m.group()), text)

    out = {}
    for kind, found in hits.items():
        ordered = []
        for _pos, label in sorted(found):
            if label not in ordered:
                ordered.append(label)
        out[kind] = tuple(ordered)
    return out


def classify(item: FeedItem) -> tuple[Classification | None, str]:
    """(classification or None, the rule that decided)."""
    text = normalize(f"{item.title} {item.summary}")
    places = _places(text)

    programs = _labels_in_order(config.PROMO_MILES_PROGRAMS, text)
    if programs and any(re.search(signal, text) for signal in config.PROMO_MILES_SIGNALS):
        return (Classification("miles", places["dest"], programs, from_bh=False, origin_unknown=False),
                f"miles:{programs[0]}")

    if _first(config.PROMO_FARE_WORDS, text) is None:
        return None, "rejected:no-fare-word"
    if not _PRICE.search(text) and _first(config.PROMO_OFFER_WORDS, text) is None:
        return None, "rejected:no-offer-signal"

    from_bh = bool(places["home"])
    if from_bh or places["dest"]:
        reason = "fare:home" if from_bh else f"fare:destination:{places['dest'][0]}"
        return Classification("fare", places["dest"], (), from_bh, origin_unknown=not from_bh), reason

    generic = _first(config.PROMO_GENERIC_TERMS, text)
    if generic:
        return Classification("fare", (), (), False, True), f"fare:generic:{generic}"
    if places["other"]:
        return None, f"rejected:other-place:{places['other'][0]}"
    return Classification("fare", (), (), False, True), "fare:no-place"
```

- [ ] **Step 5: Run the tests and watch them pass**

Run: `timeout 100 python -m pytest tests/test_promo_classify.py -q`
Expected: all pass. If `test_italy_sale…` fails on label order, the bug is in `_places` ordering, not in the test: labels follow text position ("Itália" at 0, "Roma", "Milão").

- [ ] **Step 6: Commit**

```bash
git add promos/classify.py tests/test_promo_classify.py config.py
git commit -m "feat(promos): keyword rules for fare and miles promotions

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: State, dedup and the panel payload

**Files:**
- Create: `promos/state.py`
- Test: `tests/test_promo_state.py`

**Interfaces:**
- Consumes: `FeedItem`, `Classification` (fields as above).
- Produces:
  - Constants `STATE_PATH = Path("promo_data/promos_state.json")`, `PAYLOAD_PATH = Path("promo_data/promos.json")`, `SEEN_DAYS = 30`, `PROMO_DAYS = 14`, `MAX_ATTEMPTS = 3`, `HEALTH_AFTER = 6`.
  - `PromoState` dataclass: `seen: dict[str, str]`, `promos: list[dict]`, `attempts: dict[str, int]`, `feed_failures: dict[str, int]`, `health_alerted: list[str]`, `seeding: bool`. Methods:
    - `is_seen(guid: str) -> bool`
    - `mark_seen(guid: str, now: datetime) -> None` (also drops the guid's attempt counter)
    - `add_promo(item: FeedItem, c: Classification) -> None` (idempotent per guid)
    - `record_attempt(guid: str) -> int` (returns the new count)
    - `record_feed_result(source: str, ok: bool) -> bool` (True exactly once, when the health alert must fire)
    - `payload(now: datetime) -> dict`
  - `load(path: Path = STATE_PATH) -> PromoState` — never raises; `seeding=True` when there is no usable state.
  - `save(state: PromoState, now: datetime, state_path: Path = STATE_PATH, payload_path: Path = PAYLOAD_PATH) -> None` — prunes, writes both files, never raises.

Payload shape (Portuguese keys, like `deals.json`): `{"gerado_em": "...Z", "promos": [{"tipo": "passagem"|"milhas", "titulo", "resumo", "link", "fonte", "publicado_em", "destinos": [], "programas": [], "origem_bh": bool, "origem_nao_informada": bool}]}`, newest first, no `guid`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_promo_state.py`:

```python
import json
from datetime import datetime, timedelta, timezone

from promos import state as promo_state
from promos.classify import Classification
from promos.feeds import FeedItem

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
FARE = Classification("fare", ("Roma",), (), from_bh=False, origin_unknown=True)
MILES = Classification("miles", (), ("Livelo",), from_bh=False, origin_unknown=False)


def item(guid: str, published: datetime = NOW) -> FeedItem:
    return FeedItem(guid=guid, title=f"Título {guid}", summary="Resumo", link=f"https://example.com/{guid}",
                    source="Teste", categories=(), published_at=published)


def test_missing_file_gives_an_empty_seeding_state(tmp_path):
    st = promo_state.load(tmp_path / "nada.json")
    assert st.seen == {} and st.promos == [] and st.seeding


def test_corrupt_file_gives_an_empty_seeding_state(tmp_path):
    path = tmp_path / "promos_state.json"
    path.write_text("{isto não é json", encoding="utf-8")
    assert promo_state.load(path).seeding
    path.write_text(json.dumps({"seen": "errado"}), encoding="utf-8")
    assert promo_state.load(path).seeding


def test_round_trip_keeps_everything_and_stops_seeding(tmp_path):
    st = promo_state.load(tmp_path / "s.json")
    st.mark_seen("a", NOW)
    st.add_promo(item("a"), FARE)
    st.record_attempt("b")
    st.record_feed_result("Teste", False)
    promo_state.save(st, NOW, tmp_path / "s.json", tmp_path / "p.json")

    back = promo_state.load(tmp_path / "s.json")
    assert back.is_seen("a") and not back.is_seen("b")
    assert back.promos[0]["guid"] == "a"
    assert back.attempts == {"b": 1} and back.feed_failures == {"Teste": 1}
    assert not back.seeding


def test_mark_seen_drops_the_attempt_counter():
    st = promo_state.PromoState()
    assert st.record_attempt("a") == 1 and st.record_attempt("a") == 2
    st.mark_seen("a", NOW)
    assert st.attempts == {}


def test_add_promo_is_idempotent_and_maps_the_fields():
    st = promo_state.PromoState()
    st.add_promo(item("a"), FARE)
    st.add_promo(item("a"), FARE)
    assert len(st.promos) == 1
    assert st.promos[0] == {
        "guid": "a", "tipo": "passagem", "titulo": "Título a", "resumo": "Resumo",
        "link": "https://example.com/a", "fonte": "Teste", "publicado_em": "2026-09-21T12:00:00Z",
        "destinos": ["Roma"], "programas": [], "origem_bh": False, "origem_nao_informada": True,
    }
    st.add_promo(item("m"), MILES)
    assert st.promos[1]["tipo"] == "milhas" and st.promos[1]["programas"] == ["Livelo"]


def test_save_prunes_old_guids_and_old_promos(tmp_path):
    st = promo_state.PromoState()
    st.mark_seen("velho", NOW - timedelta(days=31))
    st.mark_seen("novo", NOW - timedelta(days=29))
    st.add_promo(item("p-velha", NOW - timedelta(days=15)), FARE)
    st.add_promo(item("p-nova", NOW - timedelta(days=13)), FARE)
    promo_state.save(st, NOW, tmp_path / "s.json", tmp_path / "p.json")
    assert list(st.seen) == ["novo"]
    assert [p["guid"] for p in st.promos] == ["p-nova"]


def test_payload_is_newest_first_and_never_carries_guids(tmp_path):
    st = promo_state.PromoState()
    st.add_promo(item("antiga", NOW - timedelta(days=2)), FARE)
    st.add_promo(item("recente", NOW - timedelta(hours=1)), MILES)
    promo_state.save(st, NOW, tmp_path / "s.json", tmp_path / "p.json")
    payload = json.loads((tmp_path / "p.json").read_text(encoding="utf-8"))
    assert payload["gerado_em"] == "2026-09-21T12:00:00Z"
    assert [p["titulo"] for p in payload["promos"]] == ["Título recente", "Título antiga"]
    assert all("guid" not in p for p in payload["promos"])


def test_health_alert_fires_once_at_six_failures_and_rearms_after_a_recovery():
    st = promo_state.PromoState()
    fired = [st.record_feed_result("Teste", False) for _ in range(8)]
    assert fired == [False] * 5 + [True] + [False] * 2
    assert st.record_feed_result("Teste", True) is False
    assert st.feed_failures == {} and st.health_alerted == []
    fired = [st.record_feed_result("Teste", False) for _ in range(6)]
    assert fired[-1] is True


def test_save_never_raises_when_the_directory_cannot_be_created(tmp_path):
    blocker = tmp_path / "arquivo"
    blocker.write_text("x", encoding="utf-8")
    promo_state.save(promo_state.PromoState(), NOW, blocker / "s.json", blocker / "p.json")
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `timeout 100 python -m pytest tests/test_promo_state.py -q`
Expected: `ImportError: cannot import name 'state' from 'promos'`.

- [ ] **Step 3: Implement `promos/state.py`**

```python
"""What the promotions cycle remembers between hourly runs, in one JSON file.

The same file is the dedup memory (seen guids) and the source of the panel section (accepted
promotions of the last two weeks). It lives in promo_data/, persisted by actions/cache under
its own key: only the promotions workflow writes it, the main workflow only reads it. Losing it
costs a quiet re-seed, so load() and save() never raise.
"""
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from promos.classify import Classification
from promos.feeds import FeedItem

logger = logging.getLogger(__name__)

STATE_PATH = Path("promo_data/promos_state.json")
PAYLOAD_PATH = Path("promo_data/promos.json")
SEEN_DAYS = 30        # feeds hold a few days of posts; a month of guids is ample
PROMO_DAYS = 14       # how far back the panel section goes
MAX_ATTEMPTS = 3      # failed sends before an item is given up on
HEALTH_AFTER = 6      # consecutive failed cycles before the owner is told a feed is down
_STAMP = "%Y-%m-%dT%H:%M:%SZ"


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime(_STAMP)


def _parse(stamp: str) -> datetime:
    return datetime.strptime(stamp, _STAMP).replace(tzinfo=timezone.utc)


@dataclass
class PromoState:
    seen: dict[str, str] = field(default_factory=dict)          # guid -> when it was settled
    promos: list[dict] = field(default_factory=list)            # payload records plus "guid"
    attempts: dict[str, int] = field(default_factory=dict)      # guid -> failed sends
    feed_failures: dict[str, int] = field(default_factory=dict) # source -> consecutive failures
    health_alerted: list[str] = field(default_factory=list)     # sources already reported down
    seeding: bool = False                                       # no usable state: do not flood

    def is_seen(self, guid: str) -> bool:
        return guid in self.seen

    def mark_seen(self, guid: str, now: datetime) -> None:
        self.seen[guid] = _iso(now)
        self.attempts.pop(guid, None)

    def add_promo(self, item: FeedItem, c: Classification) -> None:
        if any(p["guid"] == item.guid for p in self.promos):
            return
        self.promos.append({
            "guid": item.guid,
            "tipo": "passagem" if c.kind == "fare" else "milhas",
            "titulo": item.title,
            "resumo": item.summary,
            "link": item.link,
            "fonte": item.source,
            "publicado_em": _iso(item.published_at),
            "destinos": list(c.destinations),
            "programas": list(c.programs),
            "origem_bh": c.from_bh,
            "origem_nao_informada": c.origin_unknown,
        })

    def record_attempt(self, guid: str) -> int:
        self.attempts[guid] = self.attempts.get(guid, 0) + 1
        return self.attempts[guid]

    def record_feed_result(self, source: str, ok: bool) -> bool:
        """True exactly once per outage: when the feed has just failed HEALTH_AFTER cycles in a row."""
        if ok:
            self.feed_failures.pop(source, None)
            if source in self.health_alerted:
                self.health_alerted.remove(source)
            return False
        self.feed_failures[source] = self.feed_failures.get(source, 0) + 1
        if self.feed_failures[source] >= HEALTH_AFTER and source not in self.health_alerted:
            self.health_alerted.append(source)
            return True
        return False

    def prune(self, now: datetime) -> None:
        seen_floor = _iso(now - timedelta(days=SEEN_DAYS))
        promo_floor = _iso(now - timedelta(days=PROMO_DAYS))
        self.seen = {g: s for g, s in self.seen.items() if s >= seen_floor}   # ISO sorts as text
        self.promos = [p for p in self.promos if p["publicado_em"] >= promo_floor]

    def payload(self, now: datetime) -> dict:
        newest_first = sorted(self.promos, key=lambda p: p["publicado_em"], reverse=True)
        return {"gerado_em": _iso(now),
                "promos": [{k: v for k, v in p.items() if k != "guid"} for p in newest_first]}


def load(path: Path = STATE_PATH) -> PromoState:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        state = PromoState(
            seen=dict(raw["seen"]), promos=list(raw["promos"]), attempts=dict(raw.get("attempts", {})),
            feed_failures=dict(raw.get("feed_failures", {})),
            health_alerted=list(raw.get("health_alerted", [])),
        )
        for stamp in state.seen.values():
            _parse(stamp)
    except FileNotFoundError:
        return PromoState(seeding=True)
    except (OSError, ValueError, KeyError, TypeError) as e:
        logger.warning(f"estado das promoções ilegível, recomeçando: {e!r}")
        return PromoState(seeding=True)
    state.seeding = not state.seen
    return state


def save(state: PromoState, now: datetime, state_path: Path = STATE_PATH,
         payload_path: Path = PAYLOAD_PATH) -> None:
    state.prune(now)
    body = {k: v for k, v in asdict(state).items() if k != "seeding"}
    try:
        for path, content in ((Path(state_path), body), (Path(payload_path), state.payload(now))):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
    except OSError as e:
        logger.error(f"estado das promoções não gravado: {e}")
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `timeout 100 python -m pytest tests/test_promo_state.py -q`
Expected: `9 passed`.

- [ ] **Step 5: Commit**

```bash
git add promos/state.py tests/test_promo_state.py
git commit -m "feat(promos): state file for dedup, counters and the panel payload

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: Telegram messages

**Files:**
- Create: `promos/notify.py`
- Test: `tests/test_promo_notify.py`

**Interfaces:**
- Consumes: `FeedItem`, `Classification`; `telegram_bot.get_bot() -> telegram.Bot`, `telegram_bot._md(text: str) -> str` (escapes `_ * ` [`), `config.TELEGRAM_CHANNEL_ID`, `config.PROMO_TOPIC_FARES`, `config.PROMO_TOPIC_MILES`.
- Produces:
  - Constants `SENT = "sent"`, `FAILED = "failed"`, `SKIPPED = "skipped"`.
  - `format_promo(item: FeedItem, c: Classification) -> str`
  - `async send_promo(item: FeedItem, c: Classification) -> str` — one of the three constants. `SKIPPED` when the topic for that kind is `None`. Never raises. Never falls back to the General thread.

`notify` reads `config.PROMO_TOPIC_*` through the module (`import config`), not `from config import …`, so the owner's later edit and the tests' monkeypatching both take effect.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_promo_notify.py`:

```python
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from telegram.error import RetryAfter, TelegramError

import config
from promos import notify
from promos.classify import Classification
from promos.feeds import FeedItem

FARE = Classification("fare", ("Roma", "Milão"), (), from_bh=False, origin_unknown=True)
FARE_BH = Classification("fare", ("Lisboa",), (), from_bh=True, origin_unknown=False)
MILES = Classification("miles", ("Lisboa",), ("Livelo", "Smiles"), from_bh=False, origin_unknown=False)


def item(title="Voos para Roma a partir de R$ 4.270", summary="Resumo curto.",
         link="https://example.com/post.html") -> FeedItem:
    return FeedItem(guid="g", title=title, summary=summary, link=link, source="Melhores Destinos",
                    categories=(), published_at=datetime(2026, 9, 21, 17, 32, tzinfo=timezone.utc))


@pytest.fixture
def bot(mocker):
    fake = mocker.Mock()
    fake.send_message = AsyncMock()
    mocker.patch("promos.notify.get_bot", return_value=fake)
    mocker.patch("promos.notify.asyncio.sleep", new=AsyncMock())
    return fake


def test_fare_message_layout():
    assert notify.format_promo(item(), FARE) == (
        "✈️ *Voos para Roma a partir de R$ 4.270*\n"
        "📍 Roma, Milão · origem não informada\n"
        "📰 Melhores Destinos · 21/09 14:32\n"
        "Resumo curto.\n"
        "🔗 [Ver a promoção](https://example.com/post.html)"
    )


def test_fare_from_bh_says_so_and_drops_the_unknown_origin_note():
    text = notify.format_promo(item(), FARE_BH)
    assert "📍 🟢 saindo de BH · Lisboa\n" in text
    assert "origem não informada" not in text


def test_fare_without_any_place():
    text = notify.format_promo(item(), Classification("fare", (), (), False, True))
    assert "📍 origem não informada\n" in text


def test_miles_message_lists_programmes_and_destinations():
    text = notify.format_promo(item(title="Resgate Smiles para Lisboa"), MILES)
    assert text.startswith("💳 *Resgate Smiles para Lisboa*\n")
    assert "🏷️ Livelo · Smiles · Lisboa\n" in text
    assert "📍" not in text


def test_markdown_specials_from_the_feed_are_escaped():
    text = notify.format_promo(item(title="Tarifa_erro *agora* [hoje]", summary="a_b `c`"), FARE)
    assert "*Tarifa\\_erro \\*agora\\* \\[hoje]*" in text
    assert "a\\_b \\`c\\`" in text


def test_long_summaries_are_cut_on_a_word_boundary():
    text = notify.format_promo(item(summary="palavra " * 60), FARE)
    summary_line = text.split("\n")[3]
    assert len(summary_line) <= 201 and summary_line.endswith("…") and not summary_line.endswith(" …")


def test_empty_summary_leaves_no_blank_line():
    assert "\n\n" not in notify.format_promo(item(summary=""), FARE)


def test_a_closing_parenthesis_in_the_link_cannot_end_the_markdown_link():
    text = notify.format_promo(item(link="https://example.com/a_(b).html"), FARE)
    assert "(https://example.com/a_(b%29.html)" in text


def test_non_https_links_are_not_rendered():
    text = notify.format_promo(item(link="javascript:alert(1)"), FARE)
    assert "🔗" not in text


async def test_fares_go_to_the_fares_topic_without_preview(bot, monkeypatch):
    monkeypatch.setattr(config, "PROMO_TOPIC_FARES", 30)
    monkeypatch.setattr(config, "PROMO_TOPIC_MILES", 32)
    assert await notify.send_promo(item(), FARE) == notify.SENT
    kwargs = bot.send_message.call_args.kwargs
    assert kwargs["message_thread_id"] == 30
    assert kwargs["link_preview_options"].is_disabled is True


async def test_miles_go_to_the_miles_topic(bot, monkeypatch):
    monkeypatch.setattr(config, "PROMO_TOPIC_FARES", 30)
    monkeypatch.setattr(config, "PROMO_TOPIC_MILES", 32)
    assert await notify.send_promo(item(), MILES) == notify.SENT
    assert bot.send_message.call_args.kwargs["message_thread_id"] == 32


async def test_unconfigured_topic_sends_nothing(bot, monkeypatch):
    monkeypatch.setattr(config, "PROMO_TOPIC_FARES", None)
    assert await notify.send_promo(item(), FARE) == notify.SKIPPED
    bot.send_message.assert_not_called()


async def test_a_failed_send_is_reported_and_never_falls_back_to_general(bot, monkeypatch):
    monkeypatch.setattr(config, "PROMO_TOPIC_FARES", 30)
    bot.send_message.side_effect = TelegramError("Bad Request: message thread not found")
    assert await notify.send_promo(item(), FARE) == notify.FAILED
    assert bot.send_message.call_count == 1


async def test_flood_control_waits_and_retries_once(bot, monkeypatch):
    monkeypatch.setattr(config, "PROMO_TOPIC_FARES", 30)
    bot.send_message.side_effect = [RetryAfter(7), None]
    assert await notify.send_promo(item(), FARE) == notify.SENT
    notify.asyncio.sleep.assert_awaited_once_with(7.0)


async def test_flood_control_wait_is_capped(bot, monkeypatch):
    monkeypatch.setattr(config, "PROMO_TOPIC_FARES", 30)
    bot.send_message.side_effect = [RetryAfter(900), RetryAfter(900)]
    assert await notify.send_promo(item(), FARE) == notify.FAILED
    notify.asyncio.sleep.assert_awaited_once_with(30.0)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `timeout 100 python -m pytest tests/test_promo_notify.py -q`
Expected: `ImportError: cannot import name 'notify' from 'promos'`.

- [ ] **Step 3: Implement `promos/notify.py`**

```python
"""Telegram side of the promotions: one message per accepted post, to the topic of its kind.

Unlike the fare alerts, a promotion whose topic is not configured is not sent at all, and a
failed send does not fall back to the General thread: the caller retries it next hour.
"""
import asyncio
import logging
from zoneinfo import ZoneInfo

from telegram import LinkPreviewOptions
from telegram.constants import ParseMode
from telegram.error import RetryAfter

import config
from promos.classify import Classification
from promos.feeds import FeedItem
from telegram_bot import _md, get_bot

logger = logging.getLogger(__name__)

SENT, FAILED, SKIPPED = "sent", "failed", "skipped"
SUMMARY_LIMIT = 200
MAX_FLOOD_WAIT_SECONDS = 30.0
_BRT = ZoneInfo("America/Sao_Paulo")


def _cut(text: str, limit: int = SUMMARY_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(" ,.;:") + "…"


def _tag_line(c: Classification) -> str:
    if c.kind == "miles":
        return "🏷️ " + " · ".join(c.programs + c.destinations)
    parts = []
    if c.from_bh:
        parts.append("🟢 saindo de BH")
    if c.destinations:
        parts.append(", ".join(c.destinations))
    if c.origin_unknown:
        parts.append("origem não informada")
    return "📍 " + " · ".join(parts)


def format_promo(item: FeedItem, c: Classification) -> str:
    when = item.published_at.astimezone(_BRT).strftime("%d/%m %H:%M")
    lines = [
        f"{'💳' if c.kind == 'miles' else '✈️'} *{_md(item.title)}*",
        _md(_tag_line(c)),
        f"📰 {_md(item.source)} · {when}",
    ]
    if item.summary:
        lines.append(_md(_cut(item.summary)))
    if item.link.startswith("https://"):
        # A ")" would close the Markdown link early.
        lines.append(f"🔗 [Ver a promoção]({item.link.replace(')', '%29')})")
    return "\n".join(lines)


def _topic_for(c: Classification) -> int | None:
    return config.PROMO_TOPIC_MILES if c.kind == "miles" else config.PROMO_TOPIC_FARES


async def send_promo(item: FeedItem, c: Classification) -> str:
    topic = _topic_for(c)
    if topic is None:
        return SKIPPED
    text = format_promo(item, c)

    async def _send() -> None:
        await get_bot().send_message(
            chat_id=config.TELEGRAM_CHANNEL_ID, text=text, parse_mode=ParseMode.MARKDOWN,
            link_preview_options=LinkPreviewOptions(is_disabled=True), message_thread_id=topic,
        )

    try:
        try:
            await _send()
        except RetryAfter as e:
            delay = e.retry_after
            seconds = delay.total_seconds() if hasattr(delay, "total_seconds") else float(delay)
            await asyncio.sleep(min(seconds, MAX_FLOOD_WAIT_SECONDS))
            await _send()
    except Exception as e:
        logger.error(f"Falha ao enviar promoção ({item.title}): {e}")
        return FAILED
    logger.info(f"Promoção enviada ao tópico {topic}: {item.title}")
    return SENT
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `timeout 100 python -m pytest tests/test_promo_notify.py -q`
Expected: `15 passed`.

- [ ] **Step 5: Commit**

```bash
git add promos/notify.py tests/test_promo_notify.py
git commit -m "feat(promos): Telegram messages routed to the fares and miles topics

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: The cycle, its entry point and the calibration script

**Files:**
- Create: `promos_main.py`, `scripts/promo_verdicts.py`
- Test: `tests/test_promos_main.py`

**Interfaces:**
- Consumes:
  - `async feeds.fetch_all(feeds, now=None, transport=None) -> tuple[list[FeedItem], dict[str, bool]]`
  - `classify(item) -> tuple[Classification | None, str]`
  - `state.load(path) -> PromoState`, `state.save(state, now, state_path, payload_path)`, the `PromoState` methods of Task 3, `state.MAX_ATTEMPTS`, `state.HEALTH_AFTER`, `state.STATE_PATH`, `state.PAYLOAD_PATH`
  - `async notify.send_promo(item, c) -> str`, `notify.SENT/FAILED/SKIPPED`
  - `async telegram_bot.send_health_alert(text: str) -> bool`
  - `config.PROMO_FEEDS`, `config.PROMO_MAX_MESSAGES_PER_CYCLE`, `config.PROMO_SEED_MAX_AGE_HOURS`
- Produces: `async promos_main.run_cycle(now: datetime | None = None, state_path: Path = state.STATE_PATH, payload_path: Path = state.PAYLOAD_PATH, transport=None) -> int` (exit code: 1 only when every feed failed) and `python promos_main.py`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_promos_main.py`:

```python
import json
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from unittest.mock import AsyncMock

import httpx
import pytest

import config
import promos_main
from promos import notify

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)


def feed(*entries: tuple[str, str, datetime]) -> bytes:
    """entries: (guid, title, published)."""
    items = "".join(
        f"<item><title>{title}</title><link>https://example.com/{guid}</link>"
        f"<guid>{guid}</guid><pubDate>{format_datetime(published)}</pubDate>"
        f"<description>Resumo.</description></item>"
        for guid, title, published in entries)
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>{items}</channel></rss>'.encode()


def transport(bodies: dict[str, bytes | None]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body = bodies[request.url.host]
        return httpx.Response(200, content=body) if body is not None else httpx.Response(500)
    return httpx.MockTransport(handler)


@pytest.fixture(autouse=True)
def two_feeds(monkeypatch):
    monkeypatch.setattr(config, "PROMO_FEEDS", [("A", "https://a.example/feed"), ("B", "https://b.example/feed")])


@pytest.fixture
def send(mocker):
    return mocker.patch("promos_main.notify.send_promo", new=AsyncMock(return_value=notify.SENT))


@pytest.fixture
def health(mocker):
    return mocker.patch("promos_main.telegram_bot.send_health_alert", new=AsyncMock(return_value=True))


def paths(tmp_path):
    return {"state_path": tmp_path / "promos_state.json", "payload_path": tmp_path / "promos.json"}


FARE = "Voos para Roma a partir de R$ 4.000"
NEWS = "Companhia anuncia novo diretor"
RECENT = NOW - timedelta(hours=1)
OLD = NOW - timedelta(hours=30)


async def test_first_run_seeds_old_posts_and_sends_only_recent_ones(tmp_path, send, health):
    t = transport({"a.example": feed(("old", FARE, OLD), ("new", FARE, RECENT)),
                   "b.example": feed(("news", NEWS, RECENT))})
    assert await promos_main.run_cycle(NOW, transport=t, **paths(tmp_path)) == 0
    assert [call.args[0].guid for call in send.await_args_list] == ["new"]
    payload = json.loads((tmp_path / "promos.json").read_text(encoding="utf-8"))
    assert len(payload["promos"]) == 2          # the old one is in the panel all the same
    state = json.loads((tmp_path / "promos_state.json").read_text(encoding="utf-8"))
    assert set(state["seen"]) == {"old", "new", "news"}


async def test_second_run_sends_nothing_again_and_old_posts_are_sent_once_seeded(tmp_path, send, health):
    first = transport({"a.example": feed(("one", FARE, RECENT)), "b.example": feed(("news", NEWS, RECENT))})
    await promos_main.run_cycle(NOW, transport=first, **paths(tmp_path))
    send.reset_mock()
    # Not seeding any more: a post with an old date that shows up now is still sent.
    second = transport({"a.example": feed(("one", FARE, RECENT), ("late", FARE, OLD)),
                        "b.example": feed(("news", NEWS, RECENT))})
    await promos_main.run_cycle(NOW + timedelta(hours=1), transport=second, **paths(tmp_path))
    assert [call.args[0].guid for call in send.await_args_list] == ["late"]


async def test_posts_are_sent_oldest_first_and_capped(tmp_path, send, health, monkeypatch):
    monkeypatch.setattr(config, "PROMO_MAX_MESSAGES_PER_CYCLE", 2)
    entries = [(f"g{n}", FARE, NOW - timedelta(minutes=n)) for n in range(5)]
    t = transport({"a.example": feed(*entries), "b.example": feed(("news", NEWS, RECENT))})
    await promos_main.run_cycle(NOW, transport=t, **paths(tmp_path))
    assert [call.args[0].guid for call in send.await_args_list] == ["g4", "g3"]
    state = json.loads((tmp_path / "promos_state.json").read_text(encoding="utf-8"))
    assert {"g0", "g1", "g2"} <= set(state["seen"])          # over the cap: panel only, not retried
    assert len(state["promos"]) == 5


async def test_a_failed_send_is_retried_and_given_up_after_three_attempts(tmp_path, send, health):
    send.return_value = notify.FAILED
    t = transport({"a.example": feed(("x", FARE, RECENT)), "b.example": feed(("news", NEWS, RECENT))})
    for hour in range(3):
        await promos_main.run_cycle(NOW + timedelta(hours=hour), transport=t, **paths(tmp_path))
    assert send.await_count == 3
    await promos_main.run_cycle(NOW + timedelta(hours=3), transport=t, **paths(tmp_path))
    assert send.await_count == 3
    state = json.loads((tmp_path / "promos_state.json").read_text(encoding="utf-8"))
    assert "x" in state["seen"] and len(state["promos"]) == 1


async def test_unconfigured_topic_marks_the_post_seen(tmp_path, send, health):
    send.return_value = notify.SKIPPED
    t = transport({"a.example": feed(("x", FARE, RECENT)), "b.example": feed(("news", NEWS, RECENT))})
    await promos_main.run_cycle(NOW, transport=t, **paths(tmp_path))
    await promos_main.run_cycle(NOW + timedelta(hours=1), transport=t, **paths(tmp_path))
    assert send.await_count == 1


async def test_one_feed_down_is_not_a_failure(tmp_path, send, health):
    t = transport({"a.example": None, "b.example": feed(("x", FARE, RECENT))})
    assert await promos_main.run_cycle(NOW, transport=t, **paths(tmp_path)) == 0
    assert send.await_count == 1


async def test_every_feed_down_exits_1_and_alerts_once_at_the_sixth_cycle(tmp_path, send, health):
    t = transport({"a.example": None, "b.example": None})
    codes = [await promos_main.run_cycle(NOW + timedelta(hours=h), transport=t, **paths(tmp_path))
             for h in range(7)]
    assert codes == [1] * 7
    assert health.await_count == 2          # one per feed, at cycle six, never again
    assert "A" in health.await_args_list[0].args[0]
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `timeout 100 python -m pytest tests/test_promos_main.py -q`
Expected: `ModuleNotFoundError: No module named 'promos_main'`.

- [ ] **Step 3: Implement `promos_main.py`**

```python
"""One pass over the promotion feeds: fetch, classify, tell Telegram, write the panel payload.

Run hourly by .github/workflows/promos.yml. Exits 1 only when every feed failed, so a single
blog being down does not turn the run red.
"""
import asyncio
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import config
import telegram_bot
from promos import feeds, notify, state
from promos.classify import classify

logger = logging.getLogger(__name__)


async def run_cycle(now: datetime | None = None, state_path: Path = state.STATE_PATH,
                    payload_path: Path = state.PAYLOAD_PATH, transport=None) -> int:
    now = now or datetime.now(timezone.utc)
    st = state.load(state_path)
    items, feed_ok = await feeds.fetch_all(config.PROMO_FEEDS, now=now, transport=transport)

    for source, ok in feed_ok.items():
        if st.record_feed_result(source, ok):
            await telegram_bot.send_health_alert(
                f"O feed de promoções {source} falhou em {state.HEALTH_AFTER} ciclos seguidos. "
                "Veja o log do workflow de promoções."
            )

    # With no state yet every post in the feeds is new; only the recent ones are worth a message.
    seed_floor = now - timedelta(hours=config.PROMO_SEED_MAX_AGE_HOURS)
    accepted = sent = held = 0
    for item in sorted(items, key=lambda i: i.published_at):
        if st.is_seen(item.guid):
            continue
        c, reason = classify(item)
        logger.info(f"promo {reason} | {item.source} | {item.title}")
        if c is None:
            st.mark_seen(item.guid, now)
            continue
        accepted += 1
        st.add_promo(item, c)
        if st.seeding and item.published_at < seed_floor:
            st.mark_seen(item.guid, now)
            continue
        if sent >= config.PROMO_MAX_MESSAGES_PER_CYCLE:
            held += 1
            st.mark_seen(item.guid, now)
            continue
        result = await notify.send_promo(item, c)
        if result == notify.FAILED:
            if st.record_attempt(item.guid) >= state.MAX_ATTEMPTS:
                logger.error(f"promoção desistida após {state.MAX_ATTEMPTS} tentativas: {item.title}")
                st.mark_seen(item.guid, now)
            continue
        if result == notify.SKIPPED:
            logger.warning(f"tópico não configurado, promoção só no painel: {item.title}")
        else:
            sent += 1
        st.mark_seen(item.guid, now)

    state.save(st, now, state_path, payload_path)
    down = [s for s, ok in feed_ok.items() if not ok]
    logger.info(
        f"CICLO PROMOS CONCLUÍDO — itens: {len(items)} | aceitas: {accepted} | enviadas: {sent} | "
        f"acima do teto: {held} | feeds fora: {len(down)}{' (' + ', '.join(down) + ')' if down else ''}"
    )
    return 1 if feed_ok and len(down) == len(feed_ok) else 0


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S")
    sys.exit(asyncio.run(run_cycle()))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `timeout 100 python -m pytest tests/test_promos_main.py -q`
Expected: `7 passed`.

- [ ] **Step 5: Write the calibration script**

Create `scripts/promo_verdicts.py` (no test: it is a read-only report over live data; `scripts/` is outside pytest's `testpaths`):

```python
"""Print every item of the live promotion feeds with the verdict the rules give it.

Read-only: sends nothing, writes nothing. Run before activating or after touching the word
lists in config.py:  python scripts/promo_verdicts.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
from promos import feeds  # noqa: E402
from promos.classify import classify  # noqa: E402


async def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    items, ok = await feeds.fetch_all(config.PROMO_FEEDS)
    for source, good in ok.items():
        print(f"# {source}: {'ok' if good else 'FALHOU'}")
    for item in sorted(items, key=lambda i: i.published_at, reverse=True):
        c, reason = classify(item)
        mark = "  --  " if c is None else ("MILHAS" if c.kind == "miles" else "PASSAG")
        print(f"{mark} | {reason:<38} | {item.source[:12]:<12} | {item.title}")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 6: Run it against the live feeds and keep the output for the owner**

Run: `python scripts/promo_verdicts.py`
Expected: two `# … : ok` lines, then about 40 lines. Check by eye that the news items are `--` and that fare sales and transfer bonuses are marked. Paste the full table in your report — the owner reviews it before anything is pushed. Do **not** tune the word lists to the output in this task; report misjudgements instead.

- [ ] **Step 7: Run the whole suite**

Run: `timeout 100 python -m pytest -q`
Expected: everything passes (291 + the new tests), no warnings about un-awaited coroutines.

- [ ] **Step 8: Commit**

```bash
git add promos_main.py scripts/promo_verdicts.py tests/test_promos_main.py
git commit -m "feat(promos): hourly cycle with seeding, message cap and feed health alert

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Encryption and the two workflows

**Files:**
- Modify: `scripts/encrypt_deals.py` (function `main`, lines 58-71)
- Modify: `tests/test_encrypt_deals.py` (append two tests)
- Create: `.github/workflows/promos.yml`
- Modify: `.github/workflows/azul-alert.yml` (one new step before "Encrypt deals and history"; one line in "Assemble site")

**Interfaces:**
- Consumes: `promo_data/promos.json` written by `state.save` (Task 3).
- Produces: `promos.enc.json` at the site root (payload v2, same password as `deals.enc.json`), read by the panel in Task 7.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_encrypt_deals.py`:

```python
def test_cli_encrypts_the_promotions_payload_when_it_exists(tmp_path):
    (tmp_path / "deals.json").write_text(json.dumps({"deals": []}), encoding="utf-8")
    (tmp_path / "promo_data").mkdir()
    promos = {"gerado_em": "2026-09-21T12:00:00Z", "promos": [{"titulo": "Promoção"}]}
    (tmp_path / "promo_data" / "promos.json").write_text(json.dumps(promos), encoding="utf-8")

    main("senha", root=str(tmp_path))

    payload = json.loads((tmp_path / "promos.enc.json").read_text(encoding="utf-8"))
    assert payload["v"] == 2
    assert json.loads(decrypt_bytes(payload, "senha")) == promos


def test_cli_without_a_promotions_payload_writes_no_promotions_file(tmp_path):
    (tmp_path / "deals.json").write_text(json.dumps({"deals": []}), encoding="utf-8")
    main("senha", root=str(tmp_path))
    assert not (tmp_path / "promos.enc.json").exists()
```

- [ ] **Step 2: Run them and watch the first one fail**

Run: `timeout 100 python -m pytest tests/test_encrypt_deals.py -q`
Expected: `test_cli_encrypts_the_promotions_payload_when_it_exists` fails with `FileNotFoundError` on `promos.enc.json`.

- [ ] **Step 3: Implement**

In `scripts/encrypt_deals.py`, replace the `main` function with:

```python
def main(password: str, root: str = ".") -> int:
    """Encrypt the snapshot, every per-route history file and the promotions payload under
    `root`. History plaintext is removed once encrypted (nothing unencrypted may be published);
    deals.json stays because the workflow's snapshot check reads it. The promotions payload is
    restored from the promotions workflow's cache and may be missing. Returns the history
    files encrypted."""
    base = Path(root)
    encrypt_file(str(base / "deals.json"), str(base / "deals.enc.json"), password)
    promos = base / "promo_data" / "promos.json"
    if promos.exists():
        encrypt_file(str(promos), str(base / "promos.enc.json"), password)
    count = 0
    for plain in sorted((base / "history").glob("*.json")):
        if plain.name.endswith(".enc.json"):
            continue
        encrypt_file(str(plain), str(plain.with_name(plain.stem + ".enc.json")), password)
        plain.unlink()
        count += 1
    return count
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `timeout 100 python -m pytest tests/test_encrypt_deals.py -q`
Expected: `9 passed`.

- [ ] **Step 5: Create `.github/workflows/promos.yml`**

```yaml
name: Promotions from RSS

on:
  schedule:
    - cron: "17 * * * *"   # hourly, off the top of the hour where GitHub delays crons the most
  workflow_dispatch: {}

concurrency:
  group: promos
  cancel-in-progress: false

permissions:
  contents: read

jobs:
  run:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip

      - name: Install deps
        run: pip install -r requirements.txt

      # Own cache key: this is the only workflow that saves promo_data/. The main workflow
      # restores it read-only, so the two never race on a save.
      - name: Restore promotions state
        uses: actions/cache@v4
        with:
          path: promo_data
          key: promos-state-${{ github.run_id }}
          restore-keys: |
            promos-state-

      - name: Run one pass
        env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHANNEL_ID: ${{ secrets.TELEGRAM_CHANNEL_ID }}
        run: python promos_main.py
```

- [ ] **Step 6: Edit `.github/workflows/azul-alert.yml`**

Insert this step immediately before the step named `Encrypt deals and history`:

```yaml
      - name: Restore promotions state (read-only)
        # Saved hourly by promos.yml; here it is only read, to ship the panel section.
        if: steps.snapshot.outputs.has_deals == 'true'
        continue-on-error: true
        uses: actions/cache/restore@v4
        with:
          path: promo_data
          key: promos-state-readonly
          restore-keys: |
            promos-state-

```

In the `Assemble site` step, add one line right after `cp deals.enc.json _site/`:

```yaml
          if [ -f promos.enc.json ]; then cp promos.enc.json _site/; fi
```

- [ ] **Step 7: Check both files still parse as YAML**

Run: `python -c "import yaml, sys; [yaml.safe_load(open(f, encoding='utf-8')) for f in ('.github/workflows/promos.yml', '.github/workflows/azul-alert.yml')]; print('ok')"`
Expected: `ok`. (If `yaml` is not installed, run `pip install pyyaml` in your own environment only — do not add it to `requirements.txt`.)

- [ ] **Step 8: Commit**

```bash
git add scripts/encrypt_deals.py tests/test_encrypt_deals.py .github/workflows/promos.yml .github/workflows/azul-alert.yml
git commit -m "feat(promos): hourly workflow; main workflow ships the encrypted promotions

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: "Promoções" section in the new panel

**Files:**
- Modify: `web/index.html` (insert after the `</section>` that closes `<section class="board" …>`, before `<div id="summary" class="counters"></div>`)
- Modify: `web/app.js` (new block after the "Decryption" block near line 73; one call inside `unlock`)
- Modify: `web/style.css` (append at the end, before any trailing `@media` block is fine — append at the very end)

**Interfaces:**
- Consumes: `promos.enc.json` at the site root; `PanelCrypto.load(url, password) -> Promise<object>` from `web/switch.js`; payload shape from Task 3.
- Produces: nothing other tasks rely on.

**Two traps in the existing code:**
1. `app.js` binds **every** `.seg` button to the cards/table view toggle (`document.querySelectorAll(".seg")`, lines ~587 and ~657). The promotions filter buttons must therefore use the class `pseg`, never `seg`.
2. There is no JS test runner. Verification is by browser, per the project routine (Step 5).

- [ ] **Step 1: Markup**

In `web/index.html`, between the board's closing `</section>` and `<div id="summary" class="counters"></div>`, insert:

```html
      <section class="promos" id="promos" aria-labelledby="promos-title" hidden>
        <div class="board-head">
          <h2 id="promos-title">Promoções</h2>
          <div class="segmented" role="group" aria-label="Filtrar promoções">
            <button type="button" class="pseg" data-promo="" aria-pressed="true">Todas</button>
            <button type="button" class="pseg" data-promo="passagem" aria-pressed="false">Passagens</button>
            <button type="button" class="pseg" data-promo="milhas" aria-pressed="false">Milhas</button>
          </div>
        </div>
        <p class="kicker" id="promos-note">publicadas nos blogs nos últimos 14 dias · origem quase nunca informada</p>
        <ol id="promo-rows" class="promo-rows"></ol>
        <p id="promo-empty" class="board-empty" hidden>Nenhuma promoção desse tipo por enquanto.</p>
        <button id="promo-more" class="btn-ghost more" type="button" hidden></button>
      </section>

```

- [ ] **Step 2: Script**

In `web/app.js`, right after the line `const loadDeals = (password) => PanelCrypto.load("deals.enc.json", password);`, insert:

```js

/* ---------------- Promotions (blog posts picked by the hourly RSS cycle) ----------------
   Optional: the file may not exist yet, and the panel must work without it. Everything in it
   was written by third parties, so it only ever reaches the page through textContent. */
const PROMO_PAGE = 8;
let PROMOS = [], PROMO_KIND = "", PROMO_SHOWN = PROMO_PAGE;

function promoAge(iso) {
  const min = Math.max(1, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (min < 60) return `há ${min} min`;
  if (min < 1440) return `há ${Math.round(min / 60)} h`;
  const days = Math.round(min / 1440);
  return days === 1 ? "ontem" : `há ${days} dias`;
}

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function promoRow(p) {
  const li = el("li", "promo-row" + (p.origem_bh ? " from-bh" : ""));
  li.append(el("span", "promo-age", promoAge(p.publicado_em)));
  li.append(el("span", "badge " + (p.tipo === "milhas" ? "rt" : "azul"), p.tipo === "milhas" ? "milhas" : "passagem"));

  const body = el("div", "promo-body");
  const safe = typeof p.link === "string" && p.link.startsWith("https://");
  const title = el(safe ? "a" : "span", "promo-title", p.titulo);
  if (safe) { title.href = p.link; title.target = "_blank"; title.rel = "noopener noreferrer"; }
  body.append(title);

  const tags = el("div", "promo-tags");
  if (p.origem_bh) tags.append(el("span", "badge low", "saindo de BH"));
  [...(p.programas || []), ...(p.destinos || [])].forEach((t) => tags.append(el("span", "badge reg", t)));
  if (p.origem_nao_informada) tags.append(el("span", "badge reg", "origem não informada"));
  tags.append(el("span", "promo-source", p.fonte));
  body.append(tags);

  li.append(body);
  return li;
}

function renderPromos() {
  const rows = PROMOS.filter((p) => !PROMO_KIND || p.tipo === PROMO_KIND);
  $("promo-rows").replaceChildren(...rows.slice(0, PROMO_SHOWN).map(promoRow));
  $("promo-empty").hidden = rows.length > 0;
  const left = rows.length - PROMO_SHOWN;
  $("promo-more").hidden = left <= 0;
  $("promo-more").textContent = `Ver mais ${Math.min(left, PROMO_PAGE)} de ${left}`;
}

function setupPromos(data) {
  PROMOS = Array.isArray(data && data.promos) ? data.promos : [];
  if (!PROMOS.length) return;          // nothing collected yet: keep the section out of the way
  $("promos").hidden = false;
  document.querySelectorAll(".pseg").forEach((b) => b.addEventListener("click", () => {
    PROMO_KIND = b.dataset.promo;
    PROMO_SHOWN = PROMO_PAGE;
    document.querySelectorAll(".pseg").forEach((o) => o.setAttribute("aria-pressed", String(o === b)));
    renderPromos();
  }));
  $("promo-more").addEventListener("click", () => { PROMO_SHOWN += PROMO_PAGE; renderPromos(); });
  renderPromos();
}

const loadPromos = (password) =>
  PanelCrypto.load("promos.enc.json", password)
    .then(setupPromos)
    .catch((e) => console.warn(`promoções indisponíveis (${e && e.code ? e.code : "erro"})`));
```

In the `unlock` function, right after the line `setup(data);`, add:

```js
    loadPromos(password);         // optional section; never blocks or fails the unlock
```

- [ ] **Step 3: Styles**

Append to the end of `web/style.css`:

```css

/* ---------------- Promotions (blog posts) ---------------- */
.promos {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  padding: var(--sp-4) var(--sp-4) var(--sp-3);
  margin-bottom: var(--sp-5);
}
.promos .board-head { margin-bottom: var(--sp-2); }
.pseg {
  display: inline-flex; align-items: center;
  min-height: 38px; padding: 0 .85rem;
  background: transparent; border: 0; border-radius: 6px;
  color: var(--text-2); font-size: .8125rem; cursor: pointer;
  transition: background .15s var(--ease), color .15s var(--ease);
}
.pseg[aria-pressed="true"] { background: var(--amber); color: #1a1203; font-weight: 600; }
.promo-rows { list-style: none; margin: var(--sp-3) 0 0; padding: 0; }
.promo-row {
  display: grid; grid-template-columns: 5.5rem 5.5rem minmax(0, 1fr);
  gap: var(--sp-3); align-items: start;
  padding: .6rem var(--sp-2);
  border-bottom: 1px solid rgb(255 255 255 / .04);
  border-left: 2px solid transparent;
}
.promo-row:last-child { border-bottom: 0; }
.promo-row.from-bh { border-left-color: var(--amber); background: rgb(255 178 26 / .05); }
.promo-age { font-family: var(--f-mono); font-size: .6875rem; letter-spacing: .06em; text-transform: uppercase; color: var(--text-3); padding-top: .2rem; }
.promo-row > .badge { justify-self: start; }
.promo-body { min-width: 0; }
.promo-title { color: var(--cream); text-decoration: none; font-weight: 500; overflow-wrap: anywhere; }
a.promo-title:hover, a.promo-title:focus-visible { color: var(--amber); text-decoration: underline; }
.promo-tags { display: flex; flex-wrap: wrap; align-items: center; gap: var(--sp-1); margin-top: var(--sp-1); }
.promo-source { font-family: var(--f-mono); font-size: .6875rem; color: var(--text-3); margin-left: var(--sp-1); }

@media (max-width: 640px) {
  .promos { padding: var(--sp-3); }
  .promo-row { grid-template-columns: auto minmax(0, 1fr); }
  .promo-row .promo-body { grid-column: 1 / -1; }
}
```

- [ ] **Step 4: Build an encrypted fixture site**

Create `_site/` by hand (it is git-ignored). Write this helper to `_site/make_fixture.py` with the Write tool (not a heredoc), then run it from the repo root with `python _site/make_fixture.py`:

```python
"""Throwaway: build an encrypted fixture site in _site/ for a browser check. Password teste123."""
import json
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.encrypt_deals import encrypt_bytes  # noqa: E402

site = Path("_site")
for name in ("index.html", "style.css", "app.js", "switch.js"):
    shutil.copy(Path("web") / name, site / name)

now = datetime.now(timezone.utc)
stamp = lambda hours: (now - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
promos = [
    {"tipo": "passagem", "titulo": "Voos saindo de Confins para Lisboa a partir de R$ 2.890 ida e volta",
     "resumo": "", "link": "https://example.com/1", "fonte": "Melhores Destinos", "publicado_em": stamp(1),
     "destinos": ["Lisboa"], "programas": [], "origem_bh": True, "origem_nao_informada": False},
    {"tipo": "milhas", "titulo": "Livelo com 100% de bônus na transferência para a Smiles <b>teste</b>",
     "resumo": "", "link": "https://example.com/2", "fonte": "Passageiro de Primeira", "publicado_em": stamp(5),
     "destinos": [], "programas": ["Livelo", "Smiles"], "origem_bh": False, "origem_nao_informada": False},
    {"tipo": "passagem", "titulo": "Link inseguro não pode virar âncora", "resumo": "",
     "link": "javascript:alert(1)", "fonte": "Teste", "publicado_em": stamp(30),
     "destinos": [], "programas": [], "origem_bh": False, "origem_nao_informada": True},
]
promos += [{"tipo": "passagem", "titulo": f"Passagens nacionais a partir de R$ {300 + n} — um título bem comprido "
            "para ver a quebra de linha no celular", "resumo": "", "link": f"https://example.com/n{n}",
            "fonte": "Melhores Destinos", "publicado_em": stamp(48 + n), "destinos": ["Roma", "Milão"],
            "programas": [], "origem_bh": False, "origem_nao_informada": True} for n in range(12)]

payload = {"gerado_em": stamp(0), "promos": promos}
(site / "promos.enc.json").write_text(
    json.dumps(encrypt_bytes(json.dumps(payload).encode("utf-8"), "teste123")), encoding="utf-8")

if not (site / "deals.enc.json").exists():
    deals = {"gerado_em": stamp(0), "deals": [], "aeroportos": {}}
    (site / "deals.enc.json").write_text(
        json.dumps(encrypt_bytes(json.dumps(deals).encode("utf-8"), "teste123")), encoding="utf-8")
print("fixture pronta em _site/")
```

If `_site/deals.enc.json` already exists from an earlier session and was encrypted with another password, delete it first so the helper rewrites it.

- [ ] **Step 5: Verify in the browser**

Serve `_site/` with `python -m http.server 8765 --directory _site` through `.claude/launch.json` and the browser preview (the controller does this step if you have no browser tool — say so in your report instead of skipping silently). With password `teste123`, check at desktop width **and** at 375 px:

1. The "Promoções" section shows between the board and the counters, 8 rows, then "Ver mais 7 de 7".
2. The "saindo de BH" row has the amber left border and the green badge.
3. The `<b>teste</b>` in the second title shows as literal text, not bold.
4. The "Link inseguro" row's title is not a link.
5. "Milhas" shows exactly one row; "Passagens" shows 8 + more; "Todas" restores.
6. The cards/table toggle below still works (the `.seg` trap).
7. No horizontal scroll at 375 px.
8. Delete `_site/promos.enc.json`, reload, unlock: the section is absent, the rest works, and the console shows one `promoções indisponíveis (http)` warning and no error.

- [ ] **Step 6: Run the whole suite**

Run: `timeout 100 python -m pytest -q`
Expected: everything passes.

- [ ] **Step 7: Commit**

```bash
git add web/index.html web/app.js web/style.css
git commit -m "feat(panel): promotions section in the new panel

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## After the last task

Activation is the owner's call and is **not** part of any task: merge `--no-ff` into `master`, push when authorised, manual `promos.yml` run with both topics `None`, owner creates the two topics and sets `PROMO_TOPIC_FARES` / `PROMO_TOPIC_MILES`, second manual run, panel check after the next main-workflow deploy (spec section 9).
