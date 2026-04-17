import pytest
from datetime import date
from unittest.mock import MagicMock, patch
from airlines.google_flights import GoogleFlightsSearcher, _parse_time, _parse_price


def test_parse_time_am():
    assert _parse_time("7:40 AM") == "07h40"

def test_parse_time_pm():
    assert _parse_time("3:05 PM") == "15h05"

def test_parse_time_noon():
    assert _parse_time("12:00 PM") == "12h00"

def test_parse_time_midnight():
    assert _parse_time("12:00 AM") == "00h00"

def test_parse_time_empty():
    assert _parse_time("") == ""

def test_parse_price_brl_symbol():
    assert _parse_price("R$289") == 289.0

def test_parse_price_with_space():
    assert _parse_price("R$ 1.290,50") == 1290.50

def test_parse_price_plain():
    assert _parse_price("450") == 450.0

def test_parse_price_invalid():
    assert _parse_price("grátis") is None
