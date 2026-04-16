import math
from datetime import date
from airlines.base import Flight


def test_flight_cache_key_format():
    flight = Flight(
        origin="CNF",
        destination="GRU",
        airline="GOL",
        departure_date=date(2026, 5, 15),
        departure_time="07h40",
        arrival_time="09h10",
        price=289.90,
        is_direct=True,
        stops=0,
        booking_url="https://example.com",
    )
    assert flight.cache_key() == "GOL|CNF|GRU|2026-05-15|280"


def test_flight_cache_key_price_floor_rounding():
    # R$350.00 → floor to 350, R$359.99 → floor to 350
    f1 = Flight("GRU", "LIS", "LATAM", date(2026, 5, 15), "10h00", "22h00", 350.00, True, 0, "https://x.com")
    f2 = Flight("GRU", "LIS", "LATAM", date(2026, 5, 15), "10h00", "22h00", 359.99, True, 0, "https://x.com")
    assert f1.cache_key() == f2.cache_key()


def test_flight_cache_key_different_price_floor():
    # R$289.90 and R$279.90 → different price floors → different keys
    f1 = Flight("CNF", "GRU", "GOL", date(2026, 5, 15), "07h40", "09h10", 289.90, True, 0, "https://x.com")
    f2 = Flight("CNF", "GRU", "GOL", date(2026, 5, 15), "07h40", "09h10", 279.90, True, 0, "https://x.com")
    assert f1.cache_key() != f2.cache_key()
