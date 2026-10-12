import pytest
from fastapi.testclient import TestClient

from ai_trader.web.app import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())
