import pytest
import cache as cache_module
from pathlib import Path


@pytest.fixture(autouse=True)
def use_tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(cache_module, "DB_PATH", tmp_path / "test_cache.db")


@pytest.fixture(autouse=True)
def use_tmp_history_db(tmp_path, monkeypatch):
    import history as history_module
    monkeypatch.setattr(history_module, "DB_PATH", tmp_path / "test_cache.db")


@pytest.fixture(autouse=True)
def use_tmp_deals_path(tmp_path, monkeypatch):
    """Keep cycle runs from overwriting the real deals.json / history.json in the repo root."""
    import cycle as cycle_module
    monkeypatch.setattr(cycle_module, "DEALS_PATH", str(tmp_path / "deals.json"))
    monkeypatch.setattr(cycle_module, "HISTORY_PATH", str(tmp_path / "history.json"))
