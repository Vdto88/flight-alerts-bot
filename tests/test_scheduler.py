import pytest
from datetime import date
from unittest.mock import AsyncMock, patch, MagicMock

from airlines.base import Flight


def _flight(price: float, airline: str = "GOL") -> Flight:
    return Flight(
        origin="CNF", destination="GRU", airline=airline,
        departure_date=date(2026, 5, 15), departure_time="07h40",
        arrival_time="09h10", price=price, is_direct=True, stops=0,
        booking_url="https://example.com",
    )


async def test_run_cycle_sends_alert_for_below_threshold(monkeypatch):
    import scheduler
    import cache
    import telegram_bot

    cheap_flight = _flight(price=289.90)  # below threshold of 350

    monkeypatch.setattr(scheduler, "SEARCHERS", {
        "GOL": MagicMock(search_range=AsyncMock(return_value=[cheap_flight]))
    })
    monkeypatch.setattr(cache, "purge_expired", AsyncMock())
    monkeypatch.setattr(cache, "is_cached", AsyncMock(return_value=False))
    monkeypatch.setattr(cache, "save_to_cache", AsyncMock())
    monkeypatch.setattr(telegram_bot, "send_alert", AsyncMock())

    from config import ROUTES
    test_route = [{"from": "CNF", "to": "GRU", "threshold": 350, "airlines": ["GOL"]}]
    monkeypatch.setattr(scheduler, "ROUTES", test_route)

    await scheduler.run_cycle()

    telegram_bot.send_alert.assert_called_once_with(cheap_flight)
    cache.save_to_cache.assert_called_once()


async def test_run_cycle_skips_cached_flight(monkeypatch):
    import scheduler
    import cache
    import telegram_bot

    flight = _flight(price=289.90)

    monkeypatch.setattr(scheduler, "SEARCHERS", {
        "GOL": MagicMock(search_range=AsyncMock(return_value=[flight]))
    })
    monkeypatch.setattr(cache, "purge_expired", AsyncMock())
    monkeypatch.setattr(cache, "is_cached", AsyncMock(return_value=True))
    monkeypatch.setattr(cache, "save_to_cache", AsyncMock())
    monkeypatch.setattr(telegram_bot, "send_alert", AsyncMock())

    monkeypatch.setattr(scheduler, "ROUTES", [
        {"from": "CNF", "to": "GRU", "threshold": 350, "airlines": ["GOL"]}
    ])

    await scheduler.run_cycle()

    telegram_bot.send_alert.assert_not_called()


async def test_run_cycle_skips_above_threshold(monkeypatch):
    import scheduler
    import cache
    import telegram_bot

    expensive = _flight(price=400.00)  # above threshold of 350

    monkeypatch.setattr(scheduler, "SEARCHERS", {
        "GOL": MagicMock(search_range=AsyncMock(return_value=[expensive]))
    })
    monkeypatch.setattr(cache, "purge_expired", AsyncMock())
    monkeypatch.setattr(cache, "is_cached", AsyncMock(return_value=False))
    monkeypatch.setattr(cache, "save_to_cache", AsyncMock())
    monkeypatch.setattr(telegram_bot, "send_alert", AsyncMock())

    monkeypatch.setattr(scheduler, "ROUTES", [
        {"from": "CNF", "to": "GRU", "threshold": 350, "airlines": ["GOL"]}
    ])

    await scheduler.run_cycle()

    telegram_bot.send_alert.assert_not_called()


async def test_run_cycle_handles_searcher_exception(monkeypatch):
    import scheduler
    import cache
    import telegram_bot

    monkeypatch.setattr(scheduler, "SEARCHERS", {
        "GOL": MagicMock(search_range=AsyncMock(side_effect=RuntimeError("API down")))
    })
    monkeypatch.setattr(cache, "purge_expired", AsyncMock())
    monkeypatch.setattr(telegram_bot, "send_alert", AsyncMock())

    monkeypatch.setattr(scheduler, "ROUTES", [
        {"from": "CNF", "to": "GRU", "threshold": 350, "airlines": ["GOL"]}
    ])

    # Should not raise — errors are swallowed and logged
    await scheduler.run_cycle()
    telegram_bot.send_alert.assert_not_called()
