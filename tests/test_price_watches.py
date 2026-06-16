from datetime import date
import config


def test_price_watch_fields():
    w = config.PriceWatch("SJK", config.month(2026, 9), 400.0)
    assert w.airport == "SJK"
    assert w.window == config.SearchWindow(date(2026, 9, 1), date(2026, 9, 30))
    assert w.max_price == 400.0


def test_price_watches_seed_entry_is_in_a_group():
    # Every watched airport must belong to some Group (for routing + topic).
    group_airports = {a for g in config.GROUPS for a in g.airports}
    for w in config.PRICE_WATCHES:
        assert w.airport in group_airports, f"{w.airport} is watched but in no Group"


def test_price_watches_has_sjk_september_example():
    by_airport = {w.airport: w for w in config.PRICE_WATCHES}
    assert "SJK" in by_airport
    assert by_airport["SJK"].window == config.month(2026, 9)
    assert by_airport["SJK"].max_price == 400.0


def test_slz_is_a_standing_watch():
    by_airport = {w.airport: w for w in config.PRICE_WATCHES}
    assert "SLZ" in by_airport
    assert by_airport["SLZ"].window is None      # standing: no fixed month
    assert by_airport["SLZ"].max_price == 600.0


def test_poa_is_a_standing_watch():
    by_airport = {w.airport: w for w in config.PRICE_WATCHES}
    assert "POA" in by_airport
    assert by_airport["POA"].window is None      # standing: rolling window only
    assert by_airport["POA"].max_price == 400.0


def test_igu_is_a_standing_watch():
    by_airport = {w.airport: w for w in config.PRICE_WATCHES}
    assert "IGU" in by_airport
    assert by_airport["IGU"].window is None      # standing: rolling window (+ group's Oct/2026)
    assert by_airport["IGU"].max_price == 500.0
