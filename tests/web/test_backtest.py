BODY = {"data": {"symbol": "BTCUSDT", "interval": "1d", "start": "2024-01-01", "end": "2025-02-03"}}
NO_SIGNALS = {k: False for k in ["trend_required", "macd_required", "rsi_required", "kdj_required", "bb_required", "pattern_required", "volume_required"]}


def test_backtest_shape(client, fake_data_source):
    r = client.post("/api/backtest/run", json=BODY)
    b = r.json()
    assert r.status_code == 200
    assert b["total_trades"] == b["winning_trades"] + b["losing_trades"] == len(b["trades"])
    assert {"total_pnl", "total_return", "max_drawdown", "sharpe_ratio", "avg_trade_duration", "win_rate"} <= set(b)
    if b["trades"]:
        assert isinstance(b["trades"][0]["entry_time"], int)


def test_backtest_no_trades_is_valid_json(client, fake_data_source):
    r = client.post("/api/backtest/run", json={**BODY, "signals": NO_SIGNALS})
    assert r.status_code == 200 and r.json()["total_trades"] == 0 and r.json()["trades"] == []


def test_backtest_params_422(client, fake_data_source):
    assert client.post("/api/backtest/run", json={**BODY, "backtest": {"position_size": "x"}}).status_code == 422


def test_backtest_uses_custom_params(client, fake_data_source):
    r = client.post("/api/backtest/run", json={**BODY, "backtest": {"initial_capital": 5000, "position_size": 0.5, "commission_rate": 0.0, "slippage_rate": 0.0}})
    assert r.status_code == 200
