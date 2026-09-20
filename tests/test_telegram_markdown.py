"""Telegram's legacy Markdown rejects a message whose text opens an entity it never closes.
An airline name with an underscore did exactly that and the alert was dropped with a 400."""
from datetime import date
from types import SimpleNamespace

import telegram_bot
from airlines.base import Flight
from airlines.google_flights import GoogleFlightsSearcher
from alerts import AzulComparison, RoundTripAlert

MARKDOWN_SPECIALS = "_*`["


def _flight(airline, origin="CNF", dest="FTE"):
    return Flight(origin, dest, airline, date(2027, 2, 10), "07h40", "", 890.0, False, 2, "https://x")


def _unescaped(text: str) -> list[str]:
    """Markdown specials in `text` that are not preceded by a backslash."""
    return [c for i, c in enumerate(text) if c in MARKDOWN_SPECIALS and (i == 0 or text[i - 1] != "\\")]


def test_md_escapes_every_legacy_markdown_special():
    assert telegram_bot._md("A_B*C`D[E") == "A\\_B\\*C\\`D\\[E"
    assert telegram_bot._md("LATAM, Tap Air Portugal") == "LATAM, Tap Air Portugal"


def test_price_alert_escapes_the_airline_name():
    msg = telegram_bot.format_price_alert(_flight("Sky_Air*line"), 1000.0)
    airline_line = next(l for l in msg.split("\n") if l.startswith("🏢"))
    assert _unescaped(airline_line) == []
    assert "Sky\\_Air\\*line" in airline_line


def test_azul_alert_escapes_the_competitor_name():
    msg = telegram_bot.format_azul_alert(_flight("Azul"), AzulComparison("Low_Cost", 990.0, 100.0))
    assert "(Low\\_Cost)" in msg


def test_round_trip_alert_escapes_both_airlines():
    rt = RoundTripAlert("Europa", _flight("Ida_Air", "CNF", "MAD"), _flight("Volta_Air", "BCN", "CNF"),
                        14, 2900.0, 3000.0)
    msg = telegram_bot.format_round_trip_alert(rt)
    assert "Ida\\_Air" in msg and "Volta\\_Air" in msg


def test_a_fare_without_an_airline_gets_a_readable_label_with_no_markdown_specials():
    result = SimpleNamespace(flights=[SimpleNamespace(
        name="", price="R$890", stops=2, departure="", arrival="")])
    flights = GoogleFlightsSearcher()._parse(result, "CNF", "FTE", date(2027, 2, 10))
    assert flights[0].airline == "Cia não informada"
    assert _unescaped(flights[0].airline) == []
