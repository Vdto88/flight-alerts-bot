from datetime import date, timedelta
import routing, config


def test_round_trip_watch_fields():
    w = config.RoundTripWatch(
        name="Europa",
        airports=("LIS", "OPO", "MAD", "BCN", "FCO", "MXP", "CDG", "ORY"),
        depart_window=config.SearchWindow(date(2027, 2, 1), date(2027, 5, 31)),
        stay_min=13, stay_max=15, max_total=3000.0, topic_id=None,
    )
    assert w.stay_min == 13 and w.stay_max == 15
    assert w.max_total == 3000.0
    assert w.topic_id is None


def test_europe_watch_is_seeded():
    by_name = {w.name: w for w in config.ROUND_TRIP_WATCHES}
    assert "Europa" in by_name
    w = by_name["Europa"]
    assert set(w.airports) == {"LIS", "OPO", "MAD", "BCN", "FCO", "MXP", "CDG", "ORY"}
    assert w.depart_window == config.SearchWindow(date(2027, 2, 1), date(2027, 5, 31))
    assert (w.stay_min, w.stay_max) == (13, 15)
    assert w.max_total == 3000.0
    assert w.topic_id is None


def test_watch_airports_all_belong_to_a_group():
    group_airports = {a for g in config.GROUPS for a in g.airports}
    for w in config.ROUND_TRIP_WATCHES:
        for a in w.airports:
            assert a in group_airports, f"{a} watched but in no Group"


def _europe_watch():
    return config.RoundTripWatch(
        name="Europa", airports=("CDG",),
        depart_window=config.SearchWindow(date(2027, 2, 1), date(2027, 5, 31)),
        stay_min=13, stay_max=15, max_total=3000.0, topic_id=None,
    )


def test_target_dates_covers_rt_span_for_pool_airport():
    today = date(2026, 8, 19)
    dates = routing.target_dates(
        "CDG", today, config.GROUPS, 30, 120, (), (_europe_watch(),)
    )
    assert date(2027, 2, 1) in dates           # depart window start
    assert date(2027, 5, 31) in dates          # depart window end
    assert date(2027, 6, 15) in dates          # end + stay_max (May 31 + 15)
    assert date(2027, 1, 31) not in dates       # just before window
    assert date(2027, 6, 16) not in dates       # just after end+stay_max


def test_target_dates_ignores_rt_span_for_non_pool_airport():
    today = date(2026, 8, 19)
    dates = routing.target_dates(
        "SLZ", today, config.GROUPS, 30, 120, (), (_europe_watch(),)
    )
    assert date(2027, 2, 1) not in dates
    assert date(2027, 6, 15) not in dates
