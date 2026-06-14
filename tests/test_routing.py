import config
import routing


def test_build_routes_both_directions_and_count():
    routes = routing.build_routes(config.GROUPS, config.AZUL_HUB)
    assert len(routes) == 42  # 21 airports x 2 directions
    pairs = {(r.origin, r.destination) for r in routes}
    assert ("CNF", "GIG") in pairs
    assert ("GIG", "CNF") in pairs
    assert all("CNF" in (r.origin, r.destination) for r in routes)


def test_build_routes_carries_non_hub_and_topic():
    routes = routing.build_routes(config.GROUPS, config.AZUL_HUB)
    igu = [r for r in routes if r.non_hub == "IGU"]
    assert len(igu) == 2
    assert all(r.topic_id is None for r in igu)  # Foz has no topic configured yet


def test_group_of_finds_group():
    g = routing.group_of("FTE", config.GROUPS)
    assert g is not None and g.name == "Patagônia"


def test_group_of_returns_none_for_unknown():
    assert routing.group_of("XXX", config.GROUPS) is None


from datetime import date, timedelta


def test_target_dates_rolling_only():
    today = date(2026, 1, 1)
    dates = routing.target_dates("GIG", today, config.GROUPS, 30, 90)
    assert dates[0] == today + timedelta(days=30)
    assert dates[-1] == today + timedelta(days=90)
    assert len(dates) == 61


def test_target_dates_includes_group_window():
    today = date(2026, 6, 1)
    dates = routing.target_dates("IGU", today, config.GROUPS, 30, 90)
    assert date(2026, 10, 1) in dates
    assert date(2026, 10, 31) in dates
    assert any(d > today + timedelta(days=90) for d in dates)  # beyond rolling end


def test_target_dates_dedups_overlapping_window():
    today = date(2026, 1, 1)
    custom = [config.Group("T", ("ZZZ",),
                           (config.SearchWindow(date(2026, 2, 1), date(2026, 2, 5)),))]
    dates = routing.target_dates("ZZZ", today, custom, 30, 90)
    assert dates == sorted(dates)
    assert len(dates) == len(set(dates))
    assert len(dates) == 61  # Feb 1-5 already inside the Jan31..Apr1 rolling range


def test_target_dates_drops_fully_past_window():
    today = date(2026, 1, 1)
    custom = [config.Group("T", ("ZZZ",),
                           (config.SearchWindow(date(2020, 1, 1), date(2020, 1, 31)),))]
    dates = routing.target_dates("ZZZ", today, custom, 30, 90)
    assert all(d >= today for d in dates)
    assert date(2020, 1, 15) not in dates
    assert len(dates) == 61  # rolling only
