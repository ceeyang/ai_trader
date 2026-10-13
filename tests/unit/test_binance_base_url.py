from ai_trader.core.data.providers.binance import BinanceDataSource

DEFAULT = "https://api.binance.com/api/v3"
MIRROR = "https://data-api.binance.vision/api/v3"


def test_default_base_url(monkeypatch):
    monkeypatch.delenv("BINANCE_BASE_URL", raising=False)
    ds = BinanceDataSource()
    assert ds.base_url == DEFAULT
    assert ds.klines_url == f"{DEFAULT}/klines"


def test_env_var_overrides_base_url(monkeypatch):
    monkeypatch.setenv("BINANCE_BASE_URL", MIRROR + "/")
    ds = BinanceDataSource()
    assert ds.base_url == MIRROR  # trailing slash stripped
    assert ds.klines_url == f"{MIRROR}/klines"
    assert ds.ticker_url == f"{MIRROR}/ticker/price"
    assert ds.exchange_info_url == f"{MIRROR}/exchangeInfo"


def test_config_overrides_env(monkeypatch):
    monkeypatch.setenv("BINANCE_BASE_URL", MIRROR)
    ds = BinanceDataSource({"base_url": "https://example.test/api/v3"})
    assert ds.base_url == "https://example.test/api/v3"
