import pytest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from airlines.azul import AzulSearcher


SAMPLE_AZUL_HTML = """
<html><body>
  <div class="fare-item">
    <span class="price-amount">R$ 389,90</span>
    <span class="departure-time">08:15</span>
    <span class="arrival-time">10:30</span>
    <span class="stops-info">Direto</span>
  </div>
  <div class="fare-item">
    <span class="price-amount">R$ 299,00</span>
    <span class="departure-time">14:00</span>
    <span class="arrival-time">17:30</span>
    <span class="stops-info">1 escala</span>
  </div>
</html>
"""

EMPTY_HTML = "<html><body><div>Carregando...</div></body></html>"


def test_parse_returns_empty_on_js_only_page():
    searcher = AzulSearcher()
    flights = searcher._parse(EMPTY_HTML, "CNF", "SSA", date(2026, 5, 15))
    assert flights == []


async def test_search_logs_todo_when_page_empty():
    searcher = AzulSearcher()
    mock_response = MagicMock()
    mock_response.text = EMPTY_HTML
    mock_response.raise_for_status = MagicMock()

    with patch("airlines.azul.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        flights = await searcher.search("CNF", "SSA", date(2026, 5, 15))

    assert flights == []


async def test_search_returns_empty_on_403():
    searcher = AzulSearcher()
    mock_response = MagicMock()
    mock_response.status_code = 403
    err = httpx.HTTPStatusError("403", request=MagicMock(), response=mock_response)

    with patch("airlines.azul.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=err)
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        flights = await searcher.search("CNF", "SSA", date(2026, 5, 15))

    assert flights == []
