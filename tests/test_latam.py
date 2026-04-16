import pytest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from airlines.latam import LatamSearcher


SAMPLE_LATAM_RESPONSE = {
    "itineraries": [
        {
            "segments": [
                {
                    "departure": {"iataCode": "GRU", "at": "2026-05-15T10:00:00"},
                    "arrival": {"iataCode": "LIS", "at": "2026-05-15T22:00:00"},
                    "numberOfStops": 0,
                }
            ],
            "price": {"grandTotal": "1800.00"},
        }
    ]
}


def test_parse_valid_response():
    searcher = LatamSearcher()
    flights = searcher._parse(SAMPLE_LATAM_RESPONSE, "GRU", "LIS", date(2026, 5, 15))
    assert len(flights) == 1
    f = flights[0]
    assert f.airline == "LATAM"
    assert f.price == 1800.00
    assert f.origin == "GRU"
    assert f.destination == "LIS"
    assert f.stops == 0
    assert f.is_direct is True


def test_parse_filters_two_plus_stops():
    data = {
        "itineraries": [
            {
                "segments": [
                    {"departure": {"at": "2026-05-15T10:00:00"}, "arrival": {"at": "2026-05-15T14:00:00"}, "numberOfStops": 2},
                ],
                "price": {"grandTotal": "900.00"},
            }
        ]
    }
    searcher = LatamSearcher()
    assert searcher._parse(data, "GRU", "LIS", date(2026, 5, 15)) == []


def test_parse_empty_response():
    searcher = LatamSearcher()
    assert searcher._parse({}, "GRU", "LIS", date(2026, 5, 15)) == []


async def test_search_returns_flights_on_200():
    searcher = LatamSearcher()
    mock_response = MagicMock()
    mock_response.json.return_value = SAMPLE_LATAM_RESPONSE
    mock_response.raise_for_status = MagicMock()

    with patch("airlines.latam.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        flights = await searcher.search("GRU", "LIS", date(2026, 5, 15))

    assert len(flights) == 1


async def test_search_returns_empty_on_403():
    searcher = LatamSearcher()
    mock_response = MagicMock()
    mock_response.status_code = 403
    err = httpx.HTTPStatusError("403", request=MagicMock(), response=mock_response)

    with patch("airlines.latam.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=err)
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        flights = await searcher.search("GRU", "LIS", date(2026, 5, 15))

    assert flights == []
