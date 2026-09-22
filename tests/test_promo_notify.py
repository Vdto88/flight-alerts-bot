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
