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
