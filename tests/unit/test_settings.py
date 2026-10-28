from decimal import Decimal

from ai_trader.settings import Settings


def test_defaults_point_to_testnet(monkeypatch):
    monkeypatch.delenv("BINANCE_TESTNET", raising=False)
    s = Settings(_env_file=None)
    assert s.binance_testnet is True
    assert s.effective_rest_url == "https://testnet.binancefuture.com"
    assert s.effective_ws_url == "wss://stream.binancefuture.com"
    assert s.mode == "paper"
    assert s.symbols == ["BTCUSDT", "ETHUSDT"]
    assert s.risk.max_order_notional_usdt == Decimal("200")  # noqa: FURB157
    assert s.llm.model == "deepseek-chat"


def test_mainnet_urls_when_testnet_false():
    s = Settings(_env_file=None, binance_testnet=False)
    assert s.effective_rest_url == "https://fapi.binance.com"
    assert s.effective_ws_url == "wss://fstream.binance.com"


def test_nested_env_override(monkeypatch):
    monkeypatch.setenv("RISK__MAX_LEVERAGE", "5")
    monkeypatch.setenv("NEWS__X_DAILY_READ_BUDGET", "100")
    s = Settings(_env_file=None)
    assert s.risk.max_leverage == 5 and s.news.x_daily_read_budget == 100


def test_secrets_not_in_repr(monkeypatch):
    monkeypatch.setenv("BINANCE_API_SECRET", "topsecret")
    s = Settings(_env_file=None)
    assert "topsecret" not in repr(s) and "topsecret" not in str(s.model_dump())


def test_configure_logging_quiets_httpx_loggers():
    import logging

    from ai_trader.logging_setup import configure_logging

    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    try:
        configure_logging("DEBUG", json_format=False)
        assert logging.getLogger("httpx").level == logging.WARNING
        assert logging.getLogger("httpcore").level == logging.WARNING
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)
