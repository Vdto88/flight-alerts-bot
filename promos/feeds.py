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
    text = BeautifulSoup(html or "", "html.parser").get_text(" ")
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
