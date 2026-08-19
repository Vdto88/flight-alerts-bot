from datetime import date
import config
from airlines.base import Flight
from alerts import evaluate_round_trip, round_trip_cache_key


def leg(origin, dest, d, price, airline="AZUL"):
    return Flight(
        origin=origin, destination=dest, airline=airline,
        departure_date=d, departure_time="10h00", arrival_time="20h00",
        price=price, is_direct=False, stops=1,
        booking_url=f"http://x/{origin}{dest}/{d}",
    )


WATCH = config.RoundTripWatch(
    name="Europa", airports=("CDG", "MXP", "LIS"),
    depart_window=config.SearchWindow(date(2027, 3, 1), date(2027, 3, 31)),
    stay_min=13, stay_max=15, max_total=3000.0, topic_id=None,
)


def test_pairs_open_jaw_cheapest_under_threshold():
    ida = [leg("CNF", "CDG", date(2027, 3, 1), 1500.0, "AZUL"),
           leg("CNF", "MXP", date(2027, 3, 1), 1400.0, "LATAM")]   # cheaper ida = MXP
    volta = [leg("CDG", "CNF", date(2027, 3, 15), 1450.0, "AZUL"),  # +14 days
             leg("LIS", "CNF", date(2027, 3, 15), 1400.0, "TAP")]   # cheaper volta = LIS
    out = evaluate_round_trip(ida, volta, WATCH)
    assert len(out) == 1
    rt = out[0]
    assert rt.ida.destination == "MXP" and rt.volta.origin == "LIS"  # open-jaw min+min
    assert rt.stay_days == 14
    assert rt.total == 2800.0


def test_rejects_stay_outside_13_15():
    ida = [leg("CNF", "CDG", date(2027, 3, 1), 1000.0)]
    volta_12 = [leg("CDG", "CNF", date(2027, 3, 13), 1000.0)]   # 12 days
    volta_16 = [leg("CDG", "CNF", date(2027, 3, 17), 1000.0)]   # 16 days
    assert evaluate_round_trip(ida, volta_12, WATCH) == []
    assert evaluate_round_trip(ida, volta_16, WATCH) == []


def test_stay_endpoints_13_and_15_each_fire():
    ida = [leg("CNF", "CDG", date(2027, 3, 1), 1000.0)]
    volta_13 = [leg("CDG", "CNF", date(2027, 3, 14), 1000.0)]   # +13 days
    volta_15 = [leg("CDG", "CNF", date(2027, 3, 16), 1000.0)]   # +15 days
    out13 = evaluate_round_trip(ida, volta_13, WATCH)
    out15 = evaluate_round_trip(ida, volta_15, WATCH)
    assert len(out13) == 1 and out13[0].stay_days == 13
    assert len(out15) == 1 and out15[0].stay_days == 15


def test_picks_stay_that_minimizes_total():
    ida = [leg("CNF", "CDG", date(2027, 3, 1), 1000.0)]
    volta = [leg("CDG", "CNF", date(2027, 3, 14), 1900.0),   # +13, total 2900
             leg("CDG", "CNF", date(2027, 3, 15), 1500.0),   # +14, total 2500 (best)
             leg("CDG", "CNF", date(2027, 3, 16), 1800.0)]   # +15, total 2800
    out = evaluate_round_trip(ida, volta, WATCH)
    assert len(out) == 1 and out[0].total == 2500.0 and out[0].stay_days == 14


def test_not_fired_above_threshold_fired_at_exact_limit():
    ida = [leg("CNF", "CDG", date(2027, 3, 1), 1500.0)]
    over = [leg("CDG", "CNF", date(2027, 3, 15), 1500.01)]
    exact = [leg("CDG", "CNF", date(2027, 3, 15), 1500.0)]
    assert evaluate_round_trip(ida, over, WATCH) == []
    assert len(evaluate_round_trip(ida, exact, WATCH)) == 1  # total 3000.0 == max


def test_one_alert_per_departure_date():
    ida = [leg("CNF", "CDG", date(2027, 3, 1), 1000.0),
           leg("CNF", "CDG", date(2027, 3, 2), 1000.0)]
    volta = [leg("CDG", "CNF", date(2027, 3, 15), 1000.0),   # pairs with Mar 1 (+14)
             leg("CDG", "CNF", date(2027, 3, 16), 1000.0)]   # pairs with Mar 2 (+14)
    out = evaluate_round_trip(ida, volta, WATCH)
    assert {rt.ida.departure_date for rt in out} == {date(2027, 3, 1), date(2027, 3, 2)}


def test_ignores_nonpositive_prices_and_out_of_window_ida():
    ida = [leg("CNF", "CDG", date(2027, 3, 1), 0.0),           # price<=0 ignored
           leg("CNF", "CDG", date(2027, 2, 1), 100.0)]          # before depart_window
    volta = [leg("CDG", "CNF", date(2027, 3, 15), 100.0),       # would pair with Mar 1 ida (ignored, price<=0)
             leg("CDG", "CNF", date(2027, 2, 15), 100.0)]       # would pair with Feb 1 ida IF window filter were broken
    assert evaluate_round_trip(ida, volta, WATCH) == []


def test_cache_key_is_stable_and_distinguishes_combos():
    ida = [leg("CNF", "CDG", date(2027, 3, 1), 1500.0)]
    volta = [leg("CDG", "CNF", date(2027, 3, 15), 1450.0)]
    rt = evaluate_round_trip(ida, volta, WATCH)[0]
    k = round_trip_cache_key(rt)
    assert k == round_trip_cache_key(rt)          # stable
    assert k.startswith("rt:Europa|CNF-CDG|2027-03-01|CDG-CNF|2027-03-15|")
