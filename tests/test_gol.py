import pytest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from airlines.gol import GolSearcher
from airlines.base import Flight


SAMPLE_GOL_RESPONSE = {
    "requestedFlightSegmentList": [
        {
            "flightList": [
                {
                    "airline": {"code": "G3"},
                    "departure": {
                        "date": "2026-05-15",
                        "hour": "07:40",
                        "airport": {"code": "CNF"},
                    },
                    "arrival": {
                        "hour": "09:10",
                        "airport": {"code": "GRU"},
                    },
                    "stops": 0,
                    "available": True,
                    "fareList": [
                        {"type": "SMILES_AND_MONEY", "money": {"totalFare": 289.90}},
                    ],
                }
            ]
        }
    ]
}


def test_parse_valid_response():
    searcher = GolSearcher()
    flights = searcher._parse(SAMPLE_GOL_RESPONSE, "CNF", "GRU")
    assert len(flights) == 1
    f = flights[0]
    assert f.airline == "GOL"
    assert f.origin == "CNF"
    assert f.destination == "GRU"
    assert f.price == 289.90
    assert f.departure_date == date(2026, 5, 15)
    assert f.departure_time == "07h40"
    assert f.arrival_time == "09h10"
    assert f.is_direct is True
    assert f.stops == 0


def test_parse_filters_more_than_one_stop():
    data = {
        "requestedFlightSegmentList": [
            {
                "flightList": [
                    {
                        "airline": {"code": "G3"},
                        "departure": {"date": "2026-05-15", "hour": "07:40", "airport": {"code": "CNF"}},
                        "arrival": {"hour": "12:00", "airport": {"code": "GRU"}},
                        "stops": 2,
                        "available": True,
                        "fareList": [{"type": "SMILES_AND_MONEY", "money": {"totalFare": 199.00}}],
                    }
                ]
            }
        ]
    }
    searcher = GolSearcher()
    assert searcher._parse(data, "CNF", "GRU") == []


def test_parse_skips_unavailable_flights():
    data = {
        "requestedFlightSegmentList": [
            {
                "flightList": [
                    {
                        "airline": {"code": "G3"},
                        "departure": {"date": "2026-05-15", "hour": "07:40", "airport": {"code": "CNF"}},
                        "arrival": {"hour": "09:10", "airport": {"code": "GRU"}},
                        "stops": 0,
                        "available": False,
                        "fareList": [{"type": "SMILES_AND_MONEY", "money": {"totalFare": 289.90}}],
                    }
                ]
            }
        ]
    }
    searcher = GolSearcher()
    assert searcher._parse(data, "CNF", "GRU") == []


def test_parse_empty_response():
    searcher = GolSearcher()
    assert searcher._parse({}, "CNF", "GRU") == []


async def test_search_returns_flights_on_200(respx_mock=None):
    searcher = GolSearcher()
    mock_response = MagicMock()
    mock_response.json.return_value = SAMPLE_GOL_RESPONSE
    mock_response.raise_for_status = MagicMock()

    with patch("airlines.gol.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        flights = await searcher.search("CNF", "GRU", date(2026, 5, 15))

    assert len(flights) == 1
    assert flights[0].price == 289.90


async def test_search_returns_empty_on_403():
    searcher = GolSearcher()
    mock_response = MagicMock()
    mock_response.status_code = 403
    http_error = httpx.HTTPStatusError("403", request=MagicMock(), response=mock_response)

    with patch("airlines.gol.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=http_error)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        flights = await searcher.search("CNF", "GRU", date(2026, 5, 15))

    assert flights == []


async def test_search_returns_empty_on_timeout():
    searcher = GolSearcher()

    with patch("airlines.gol.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        with patch("airlines.gol.asyncio.sleep", new_callable=AsyncMock):
            flights = await searcher.search("CNF", "GRU", date(2026, 5, 15))

    assert flights == []
