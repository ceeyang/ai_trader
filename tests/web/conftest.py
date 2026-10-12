import pytest
from fastapi.testclient import TestClient

from ai_trader.web.app import create_app
from ai_trader.web.services import market_data


@pytest.fixture
def client() -> TestClient:
    market_data.reset_data_source()
    market_data.fetch_klines.cache_clear()
    return TestClient(create_app())
