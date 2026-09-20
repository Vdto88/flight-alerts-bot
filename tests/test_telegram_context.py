from datetime import date

import telegram_bot
from airlines.base import Flight
from alerts import AzulComparison
from history import HistoryContext


def _flight(price=289.0):
    return Flight("CNF", "GIG", "Azul", date(2026, 11, 20), "07h40", "08h50", price, True, 0, "https://x")


def test_below_the_median_and_lowest_since():
    ctx = HistoryContext(-38, 60, True, "2026-08-20", "data")
    assert telegram_bot.format_context_line(ctx) == \
        "📉 38% abaixo da média de 60 dias · menor preço desde 20/08\n"


def test_below_the_median_without_being_the_low():
    assert telegram_bot.format_context_line(HistoryContext(-12, 60, False, "2026-08-20", "data")) == \
        "📉 12% abaixo da média de 60 dias\n"


def test_above_the_median():
    assert telegram_bot.format_context_line(HistoryContext(12, 60, False, None, "data")) == \
        "📈 12% acima da média de 60 dias\n"


def test_within_three_percent_is_flat():
    for pct in (-3, 0, 3):
        assert telegram_bot.format_context_line(HistoryContext(pct, 60, False, None, "data")) == \
            "➖ na média de 60 dias\n"


def test_route_scope_names_the_route():
    assert telegram_bot.format_context_line(HistoryContext(-20, 60, False, None, "rota")) == \
        "📉 20% abaixo da média da rota\n"


def test_no_context_no_line():
    assert telegram_bot.format_context_line(None) == ""


def test_messages_are_byte_identical_without_context_and_gain_one_line_with_it():
    comp = AzulComparison("LATAM", 396.0, 107.0)
    ctx = HistoryContext(-38, 60, True, "2026-08-20", "data")
    plain = telegram_bot.format_azul_alert(_flight(), comp)
    rich = telegram_bot.format_azul_alert(_flight(), comp, ctx)
    assert "média" not in plain
    assert rich.count("\n") == plain.count("\n") + 1
    assert "📉 38% abaixo da média de 60 dias · menor preço desde 20/08" in rich

    plain_p = telegram_bot.format_price_alert(_flight(), 400.0)
    rich_p = telegram_bot.format_price_alert(_flight(), 400.0, ctx)
    assert rich_p.count("\n") == plain_p.count("\n") + 1
