from datetime import date

from airlines.base import Flight
from config import PriceWatch, SearchWindow
from alerts import evaluate_threshold, ThresholdAlert

SEP = SearchWindow(date(2026, 9, 1), date(2026, 9, 30))


def _f(airline, price, d=date(2026, 9, 10)):
    return Flight("CNF", "SJK", airline, d, "08h00", "09h00", price, True, 0, "u")


def test_fires_on_cheapest_any_airline_at_or_under_limit():
    flights = [_f("GOL", 380.0), _f("Azul", 420.0), _f("LATAM", 500.0)]
    alerts = evaluate_threshold(flights, [PriceWatch("SJK", SEP, 400.0)])
    assert len(alerts) == 1
    assert isinstance(alerts[0], ThresholdAlert)
    assert alerts[0].flight.airline == "GOL"
    assert alerts[0].flight.price == 380.0
    assert alerts[0].max_price == 400.0


def test_limit_is_inclusive():
    alerts = evaluate_threshold([_f("GOL", 400.0)], [PriceWatch("SJK", SEP, 400.0)])
    assert len(alerts) == 1


def test_no_fire_above_limit():
    assert evaluate_threshold([_f("GOL", 401.0)], [PriceWatch("SJK", SEP, 400.0)]) == []


def test_ignores_dates_outside_window():
    flights = [_f("GOL", 200.0, date(2026, 10, 5))]   # October, window is September
    assert evaluate_threshold(flights, [PriceWatch("SJK", SEP, 400.0)]) == []


def test_ignores_nonpositive_price():
    assert evaluate_threshold([_f("Azul", 0.0)], [PriceWatch("SJK", SEP, 400.0)]) == []


def test_no_watches_returns_empty():
    assert evaluate_threshold([_f("GOL", 100.0)], []) == []


def test_picks_tightest_satisfied_limit_when_two_watches_overlap():
    watches = [PriceWatch("SJK", SEP, 400.0), PriceWatch("SJK", SEP, 350.0)]
    alerts = evaluate_threshold([_f("GOL", 300.0)], watches)
    assert len(alerts) == 1
    assert alerts[0].max_price == 350.0   # smallest limit the fare still satisfies


def test_standing_watch_matches_any_date():
    # window=None applies to every date (no month restriction)
    flights = [_f("LATAM", 550.0, date(2099, 7, 15))]
    alerts = evaluate_threshold(flights, [PriceWatch("SLZ", None, 600.0)])
    assert len(alerts) == 1
    assert alerts[0].max_price == 600.0


def test_standing_watch_respects_limit():
    flights = [_f("LATAM", 650.0, date(2099, 7, 15))]
    assert evaluate_threshold(flights, [PriceWatch("SLZ", None, 600.0)]) == []
