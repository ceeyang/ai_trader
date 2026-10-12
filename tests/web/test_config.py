def test_get_default_when_missing(client, tmp_path, monkeypatch):
    monkeypatch.setenv("AI_TRADER_DATA_DIR", str(tmp_path))
    body = client.get("/api/config/analysis").json()
    assert body["signals"]["rsi_oversold"] == 30
    assert body["indicators"]["sma_periods"] == [5, 10, 20, 50, 200]
    assert body["backtest"]["initial_capital"] == 100000


def test_put_then_get_roundtrip(client, tmp_path, monkeypatch):
    monkeypatch.setenv("AI_TRADER_DATA_DIR", str(tmp_path))
    body = client.get("/api/config/analysis").json()
    body["signals"]["rsi_oversold"] = 25
    r = client.put("/api/config/analysis", json=body)
    assert r.status_code == 200 and r.json()["signals"]["rsi_oversold"] == 25
    assert client.get("/api/config/analysis").json()["signals"]["rsi_oversold"] == 25
    assert (tmp_path / "analysis_config.json").exists()


def test_put_invalid_422(client, tmp_path, monkeypatch):
    monkeypatch.setenv("AI_TRADER_DATA_DIR", str(tmp_path))
    assert client.put("/api/config/analysis", json={"signals": {"combination": "nope"}}).status_code == 422
