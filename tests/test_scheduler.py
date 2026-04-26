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
    monkeypatch.setattr(scheduler, "google_searcher",
        MagicMock(search_range=AsyncMock(return_value=[]))
    )
    monkeypatch.setattr(cache, "purge_expired", AsyncMock())
    monkeypatch.setattr(telegram_bot, "send_alert", AsyncMock())
    monkeypatch.setattr(scheduler, "ROUTES", [
        {"from": "CNF", "to": "GRU", "threshold": 350, "airlines": ["GOL"]}
    ])

    # Should not raise — errors are swallowed and logged
    await scheduler.run_cycle()
    telegram_bot.send_alert.assert_not_called()


def test_matches_airline_gol():
    from scheduler import _matches_airline
    assert _matches_airline("GOL Linhas Aéreas", "GOL") is True
    assert _matches_airline("Gol", "GOL") is True
    assert _matches_airline("LATAM Airlines", "GOL") is False


def test_matches_airline_latam():
    from scheduler import _matches_airline
    assert _matches_airline("LATAM Airlines", "LATAM") is True
    assert _matches_airline("Latam", "LATAM") is True
    assert _matches_airline("Azul", "LATAM") is False


def test_matches_airline_azul():
    from scheduler import _matches_airline
    assert _matches_airline("Azul Linhas Aéreas", "AZUL") is True
    assert _matches_airline("AZUL", "AZUL") is True
    assert _matches_airline("GOL", "AZUL") is False


async def test_run_cycle_uses_fallback_when_scraper_returns_empty(monkeypatch):
    import scheduler
    import cache
    import telegram_bot

    cheap_flight = _flight(price=289.90, airline="GOL Linhas Aéreas")

    monkeypatch.setattr(scheduler, "SEARCHERS", {
        "GOL": MagicMock(search_range=AsyncMock(return_value=[]))
    })
    monkeypatch.setattr(scheduler, "google_searcher",
        MagicMock(search_range=AsyncMock(return_value=[cheap_flight]))
    )
    monkeypatch.setattr(cache, "purge_expired", AsyncMock())
    monkeypatch.setattr(cache, "is_cached", AsyncMock(return_value=False))
    monkeypatch.setattr(cache, "save_to_cache", AsyncMock())
    monkeypatch.setattr(telegram_bot, "send_alert", AsyncMock())
    monkeypatch.setattr(scheduler, "ROUTES", [
        {"from": "CNF", "to": "GRU", "threshold": 350, "airlines": ["GOL"]}
    ])

    await scheduler.run_cycle()

    telegram_bot.send_alert.assert_called_once_with(cheap_flight)


async def test_run_cycle_fallback_filters_wrong_airline(monkeypatch):
    import scheduler
    import cache
    import telegram_bot

    latam_flight = _flight(price=289.90, airline="LATAM Airlines")

    monkeypatch.setattr(scheduler, "SEARCHERS", {
        "GOL": MagicMock(search_range=AsyncMock(return_value=[]))
    })
    monkeypatch.setattr(scheduler, "google_searcher",
        MagicMock(search_range=AsyncMock(return_value=[latam_flight]))
    )
    monkeypatch.setattr(cache, "purge_expired", AsyncMock())
    monkeypatch.setattr(cache, "is_cached", AsyncMock(return_value=False))
    monkeypatch.setattr(cache, "save_to_cache", AsyncMock())
    monkeypatch.setattr(telegram_bot, "send_alert", AsyncMock())
    monkeypatch.setattr(scheduler, "ROUTES", [
        {"from": "CNF", "to": "GRU", "threshold": 350, "airlines": ["GOL"]}
    ])

    await scheduler.run_cycle()

    telegram_bot.send_alert.assert_not_called()


async def test_run_cycle_uses_fallback_on_exception(monkeypatch):
    import scheduler
    import cache
    import telegram_bot

    cheap_flight = _flight(price=289.90, airline="GOL Linhas Aéreas")

    monkeypatch.setattr(scheduler, "SEARCHERS", {
        "GOL": MagicMock(search_range=AsyncMock(side_effect=RuntimeError("API down")))
    })
    monkeypatch.setattr(scheduler, "google_searcher",
        MagicMock(search_range=AsyncMock(return_value=[cheap_flight]))
    )
    monkeypatch.setattr(cache, "purge_expired", AsyncMock())
    monkeypatch.setattr(cache, "is_cached", AsyncMock(return_value=False))
    monkeypatch.setattr(cache, "save_to_cache", AsyncMock())
    monkeypatch.setattr(telegram_bot, "send_alert", AsyncMock())
    monkeypatch.setattr(scheduler, "ROUTES", [
        {"from": "CNF", "to": "GRU", "threshold": 350, "airlines": ["GOL"]}
    ])

    await scheduler.run_cycle()

    telegram_bot.send_alert.assert_called_once_with(cheap_flight)


def _miles_flight(miles: int, airline: str = "SMILES") -> Flight:
    return Flight(
        origin="CNF", destination="IGU", airline=airline,
        departure_date=date(2026, 7, 15), departure_time="07h40",
        arrival_time="09h10", price=0.0, is_direct=True, stops=0,
        booking_url="https://smiles.com.br",
        miles=miles,
    )


async def test_run_miles_cycle_sends_alert_below_threshold(monkeypatch):
    import scheduler
    import cache
    import telegram_bot

    cheap = _miles_flight(miles=14000, airline="SMILES")

    monkeypatch.setattr(scheduler, "MILES_SEARCHERS", {
        "SMILES": MagicMock(search_range=AsyncMock(return_value=[cheap]))
    })
    monkeypatch.setattr(cache, "is_cached", AsyncMock(return_value=False))
    monkeypatch.setattr(cache, "save_to_cache", AsyncMock())
    monkeypatch.setattr(telegram_bot, "send_alert", AsyncMock())
    monkeypatch.setattr(scheduler, "MILES_ROUTES", [
        {"from": "CNF", "to": "IGU", "miles_threshold": 15000, "program": "SMILES"}
    ])

    await scheduler.run_miles_cycle()

    telegram_bot.send_alert.assert_called_once_with(cheap)
    cache.save_to_cache.assert_called_once()


async def test_run_miles_cycle_sends_alert_at_exact_threshold(monkeypatch):
    import scheduler
    import cache
    import telegram_bot

    exact = _miles_flight(miles=15000, airline="SMILES")

    monkeypatch.setattr(scheduler, "MILES_SEARCHERS", {
        "SMILES": MagicMock(search_range=AsyncMock(return_value=[exact]))
    })
    monkeypatch.setattr(cache, "is_cached", AsyncMock(return_value=False))
    monkeypatch.setattr(cache, "save_to_cache", AsyncMock())
    monkeypatch.setattr(telegram_bot, "send_alert", AsyncMock())
    monkeypatch.setattr(scheduler, "MILES_ROUTES", [
        {"from": "CNF", "to": "IGU", "miles_threshold": 15000, "program": "SMILES"}
    ])

    await scheduler.run_miles_cycle()

    telegram_bot.send_alert.assert_called_once_with(exact)


async def test_run_miles_cycle_skips_above_threshold(monkeypatch):
    import scheduler
    import cache
    import telegram_bot

    expensive = _miles_flight(miles=16000, airline="SMILES")

    monkeypatch.setattr(scheduler, "MILES_SEARCHERS", {
        "SMILES": MagicMock(search_range=AsyncMock(return_value=[expensive]))
    })
    monkeypatch.setattr(cache, "is_cached", AsyncMock(return_value=False))
    monkeypatch.setattr(cache, "save_to_cache", AsyncMock())
    monkeypatch.setattr(telegram_bot, "send_alert", AsyncMock())
    monkeypatch.setattr(scheduler, "MILES_ROUTES", [
        {"from": "CNF", "to": "IGU", "miles_threshold": 15000, "program": "SMILES"}
    ])

    await scheduler.run_miles_cycle()

    telegram_bot.send_alert.assert_not_called()


async def test_run_miles_cycle_skips_cached(monkeypatch):
    import scheduler
    import cache
    import telegram_bot

    cheap = _miles_flight(miles=14000, airline="SMILES")

    monkeypatch.setattr(scheduler, "MILES_SEARCHERS", {
        "SMILES": MagicMock(search_range=AsyncMock(return_value=[cheap]))
    })
    monkeypatch.setattr(cache, "is_cached", AsyncMock(return_value=True))
    monkeypatch.setattr(cache, "save_to_cache", AsyncMock())
    monkeypatch.setattr(telegram_bot, "send_alert", AsyncMock())
    monkeypatch.setattr(scheduler, "MILES_ROUTES", [
        {"from": "CNF", "to": "IGU", "miles_threshold": 15000, "program": "SMILES"}
    ])

    await scheduler.run_miles_cycle()

    telegram_bot.send_alert.assert_not_called()
