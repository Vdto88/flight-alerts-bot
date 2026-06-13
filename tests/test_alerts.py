from datetime import date

from airlines.base import Flight
from alerts import evaluate, AzulAlert, AzulComparison


def _f(airline, price, dep=date(2026, 7, 15), stops=0):
    return Flight("CNF", "SSA", airline, dep, "12h00", "13h15",
                  price, stops == 0, stops, "https://book")


def test_azul_cheapest_fires_with_comparison():
    flights = [_f("Azul", 300.0), _f("LATAM", 396.0), _f("Gol", 410.0)]
    alerts = evaluate(flights)
    assert len(alerts) == 1
    a = alerts[0]
    assert isinstance(a, AzulAlert)
    assert a.flight.airline == "Azul"
    assert a.comparison == AzulComparison(competitor="LATAM",
                                          competitor_price=396.0, savings=96.0)


def test_no_alert_when_competitor_cheaper():
    flights = [_f("Azul", 400.0), _f("LATAM", 396.0)]
    assert evaluate(flights) == []


def test_no_alert_on_tie():
    flights = [_f("Azul", 396.0), _f("LATAM", 396.0)]
    assert evaluate(flights) == []


def test_no_alert_when_azul_is_only_airline():
    flights = [_f("Azul", 300.0), _f("Azul", 320.0)]
    assert evaluate(flights) == []


def test_no_alert_when_no_azul():
    flights = [_f("LATAM", 300.0), _f("Gol", 320.0)]
    assert evaluate(flights) == []


def test_picks_cheapest_azul_and_cheapest_competitor():
    flights = [_f("Azul", 350.0), _f("Azul", 300.0),
               _f("LATAM", 500.0), _f("Gol", 396.0)]
    alerts = evaluate(flights)
    assert len(alerts) == 1
    assert alerts[0].flight.price == 300.0
    assert alerts[0].comparison.competitor == "Gol"
    assert alerts[0].comparison.savings == 96.0


def test_each_date_evaluated_independently():
    d1, d2 = date(2026, 7, 15), date(2026, 7, 16)
    flights = [
        _f("Azul", 300.0, dep=d1), _f("LATAM", 396.0, dep=d1),   # fires
        _f("Azul", 500.0, dep=d2), _f("LATAM", 396.0, dep=d2),   # no
    ]
    alerts = evaluate(flights)
    assert {a.flight.departure_date for a in alerts} == {d1}


def test_ignores_zero_or_missing_price():
    flights = [_f("Azul", 0.0), _f("Azul", 300.0), _f("LATAM", 396.0)]
    alerts = evaluate(flights)
    assert len(alerts) == 1
    assert alerts[0].flight.price == 300.0


def test_stops_not_filtered():
    # A 2-stop Azul still wins if it is cheaper.
    flights = [_f("Azul", 300.0, stops=2), _f("LATAM", 396.0, stops=0)]
    alerts = evaluate(flights)
    assert len(alerts) == 1
    assert alerts[0].flight.stops == 2
