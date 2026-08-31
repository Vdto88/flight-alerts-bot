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
