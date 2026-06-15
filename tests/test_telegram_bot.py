import pytest
from datetime import date
from unittest.mock import AsyncMock, patch, MagicMock

from airlines.base import Flight
import telegram_bot


def _sample_flight(price: float = 289.90) -> Flight:
    return Flight(
        origin="CNF",
        destination="GRU",
        airline="GOL",
        departure_date=date(2026, 5, 15),
        departure_time="07h40",
        arrival_time="09h10",
        price=price,
        is_direct=True,
        stops=0,
        booking_url="https://example.com/book",
    )


def test_format_alert_contains_route():
    msg = telegram_bot.format_alert(_sample_flight())
    assert "CNF → GRU" in msg


def test_format_alert_contains_price():
    msg = telegram_bot.format_alert(_sample_flight(289.90))
    assert "289,90" in msg


def test_format_alert_contains_date():
    msg = telegram_bot.format_alert(_sample_flight())
    assert "15/05/2026" in msg


def test_format_alert_contains_airline():
    msg = telegram_bot.format_alert(_sample_flight())
    assert "GOL" in msg


def test_format_alert_direct_flight_label():
    msg = telegram_bot.format_alert(_sample_flight())
    assert "Direto" in msg


def test_format_alert_one_stop_label():
    flight = _sample_flight()
    flight.is_direct = False
    flight.stops = 1
    msg = telegram_bot.format_alert(flight)
    assert "1 parada" in msg


async def test_send_alert_calls_telegram(monkeypatch):
    mock_bot = AsyncMock()
    mock_bot.send_message = AsyncMock()
    monkeypatch.setattr(telegram_bot, "get_bot", lambda: mock_bot)

    await telegram_bot.send_alert(_sample_flight())

    mock_bot.send_message.assert_called_once()
    call_kwargs = mock_bot.send_message.call_args.kwargs
    assert "CNF → GRU" in call_kwargs["text"]


def _sample_miles_flight(miles: int = 15000, airline: str = "SMILES") -> Flight:
    return Flight(
        origin="CNF",
        destination="IGU",
        airline=airline,
        departure_date=date(2026, 7, 15),
        departure_time="07h40",
        arrival_time="09h10",
        price=0.0,
        is_direct=True,
        stops=0,
        booking_url="https://smiles.com.br/busca",
        miles=miles,
    )


def test_miles_alert_contains_miles_value():
    msg = telegram_bot.format_alert(_sample_miles_flight(15000))
    assert "15.000 milhas" in msg


def test_miles_alert_contains_route():
    msg = telegram_bot.format_alert(_sample_miles_flight())
    assert "CNF → IGU" in msg


def test_miles_alert_contains_airline():
    msg = telegram_bot.format_alert(_sample_miles_flight(airline="SMILES"))
    assert "SMILES" in msg or "Smiles" in msg


def test_miles_alert_contains_date():
    msg = telegram_bot.format_alert(_sample_miles_flight())
    assert "15/07/2026" in msg


def test_miles_alert_uses_milhas_header():
    msg = telegram_bot.format_alert(_sample_miles_flight())
    assert "MILHAS" in msg.upper()


def test_miles_alert_does_not_show_brl_price():
    msg = telegram_bot.format_alert(_sample_miles_flight())
    assert "R$" not in msg


def test_money_alert_unchanged():
    # Regression: money alert must not change
    money_flight = _sample_flight()
    msg = telegram_bot.format_alert(money_flight)
    assert "289,90" in msg
    assert "PASSAGEM BARATA" in msg.upper()


def test_miles_alert_direct_flight():
    msg = telegram_bot.format_alert(_sample_miles_flight())
    assert "Direto" in msg


def test_miles_alert_azul():
    msg = telegram_bot.format_alert(_sample_miles_flight(miles=20000, airline="AZUL_MILES"))
    assert "20.000 milhas" in msg
    assert "AZUL" in msg.upper()


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
