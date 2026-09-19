import pytest
from datetime import date
from unittest.mock import AsyncMock, patch, MagicMock

from airlines.base import Flight
import telegram_bot


from datetime import date as _date
from airlines.base import Flight as _Flight
from alerts import AzulComparison as _AzulComparison
import telegram_bot as _tb


def test_format_azul_alert_contains_comparison():
    f = _Flight("CNF", "SSA", "Azul", _date(2026, 7, 15), "12h00", "13h15",
                300.0, True, 0, "https://book")
    comp = _AzulComparison(competitor="LATAM", competitor_price=396.0, savings=96.0)
    msg = _tb.format_azul_alert(f, comp)
    assert "AZUL É A MAIS BARATA" in msg
    assert "CNF → SSA" in msg
    assert "R$ 300,00" in msg
    assert "LATAM" in msg
    assert "R$ 396,00" in msg
    assert "economia de R$ 96,00" in msg
    assert "Direto" in msg
    assert "https://book" in msg


def test_format_azul_alert_shows_stops_plural():
    f = _Flight("CNF", "PUQ", "Azul", _date(2026, 7, 15), "06h00", "20h00",
                900.0, False, 2, "https://book")
    comp = _AzulComparison(competitor="LATAM", competitor_price=1200.0, savings=300.0)
    msg = _tb.format_azul_alert(f, comp)
    assert "2 paradas" in msg


async def test_send_azul_alert_swallows_errors(monkeypatch):
    # A failure building the bot (e.g. missing/invalid token) must not crash the
    # cycle — it should be logged and swallowed.
    def boom():
        raise RuntimeError("no token")
    monkeypatch.setattr(_tb, "get_bot", boom)
    f = _Flight("CNF", "SSA", "Azul", _date(2026, 7, 15), "12h00", "13h15",
                300.0, True, 0, "https://book")
    comp = _AzulComparison(competitor="LATAM", competitor_price=396.0, savings=96.0)
    result = await _tb.send_azul_alert(f, comp)   # must not raise
    assert result is False


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
