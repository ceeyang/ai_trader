BODY = {"data": {"symbol": "BTCUSDT", "interval": "1d", "start": "2024-01-01", "end": "2025-02-03"}}


def test_analysis_run_shape(client, fake_data_source):
    r = client.post("/api/analysis/run", json=BODY)
    b = r.json()
    assert r.status_code == 200
    assert set(b) == {"indicators", "patterns", "entry_signals", "exit_signals", "effectiveness"}
    assert len(b["indicators"]["rsi"]) == 400
    assert all(isinstance(t, int) for t in b["entry_signals"])
    assert all({"frequency", "avg_price_change_1d", "positive_rate"} == set(v) for v in b["effectiveness"].values())


def test_analysis_matches_signal_config(client, fake_data_source, sample_ohlcv):
    from ai_trader.core.analysis.signals import SignalConfig, SignalDetector

    r = client.post("/api/analysis/run", json={**BODY, "signals": {"combination": "min", "min_conditions": 2}})
    expected = SignalDetector(sample_ohlcv).get_custom_entry_signals(SignalConfig(combination="min", min_conditions=2))
    assert r.json()["entry_signals"] == [int(t.timestamp()) for t in sample_ohlcv.index[expected]]


def test_analysis_empty_range_422(client, fake_data_source):
    r = client.post("/api/analysis/run", json={"data": {"symbol": "BTCUSDT", "interval": "1d", "start": "2030-01-01", "end": "2030-01-02"}})
    assert r.status_code == 422


def test_analysis_bad_combination_422(client, fake_data_source):
    assert client.post("/api/analysis/run", json={**BODY, "signals": {"combination": "sometimes"}}).status_code == 422
