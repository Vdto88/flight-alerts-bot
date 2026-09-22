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
