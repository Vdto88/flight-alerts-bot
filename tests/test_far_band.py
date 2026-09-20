from datetime import date, timedelta

import cache
import config
import cycle
import main
import routing
from airlines.base import Flight
from airlines.google_flights import GoogleFlightsSearcher

TODAY = date(2026, 9, 20)


def test_near_cycle_stops_at_the_near_band():
    dates = routing.target_dates("GIG", TODAY, config.GROUPS, 30, 120)
    assert dates[0] == TODAY + timedelta(days=30)
    assert dates[-1] == TODAY + timedelta(days=120)


def test_far_cycle_extends_the_rolling_range():
    dates = routing.target_dates("GIG", TODAY, config.GROUPS, 30, 120, far_max=180)
    assert dates[-1] == TODAY + timedelta(days=180)
    assert len(dates) == 151


def test_explicit_windows_are_searched_in_both_kinds_of_cycle():
    feb = date(2027, 2, 15)      # Patagônia group window, beyond the near band on TODAY
    assert feb in routing.target_dates("FTE", TODAY, config.GROUPS, 30, 120)
    assert feb in routing.target_dates("FTE", TODAY, config.GROUPS, 30, 120, far_max=180)


def test_far_dates_requested_only_for_the_exact_flag():
    assert main.far_dates_requested({"SEARCH_FAR_DATES": "1"}) is True
    for value in ("0", "", "true", "yes"):
        assert main.far_dates_requested({"SEARCH_FAR_DATES": value}) is False
    assert main.far_dates_requested({}) is False


async def _run_and_capture_dates(monkeypatch, include_far):
    import telegram_bot
    await cache.init_db()
    seen: dict[tuple, list] = {}

    async def fake_search_dates(self, origin, destination, dates, batch_size=7):
        seen[(origin, destination)] = dates
        d = dates[0]
        return [Flight(origin, destination, "LATAM", d, "07h00", "08h00", 300.0, True, 0, "u")]

    async def ok(*args, **kwargs):
        return True

    monkeypatch.setattr(GoogleFlightsSearcher, "search_dates", fake_search_dates)
    for name in ("send_azul_alert", "send_price_alert", "send_round_trip_alert"):
        monkeypatch.setattr(telegram_bot, name, ok)
    await cycle.run_azul_cycle(include_far=include_far)
    return seen[("CNF", "GIG")]


async def test_cycle_searches_the_far_band_only_when_asked(monkeypatch):
    limit = date.today() + timedelta(days=config.WINDOW_MAX_DAYS)
    near = await _run_and_capture_dates(monkeypatch, include_far=False)
    assert max(near) == limit
    far = await _run_and_capture_dates(monkeypatch, include_far=True)
    assert max(far) == date.today() + timedelta(days=config.WINDOW_FAR_MAX_DAYS)
