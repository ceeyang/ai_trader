"""Fix-pass tests for the whole-branch review (C1, I1, I2, I3, I4, I7)."""

from datetime import date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ai_trader.web.app import create_app


# C1 — timestamps must round-trip Binance ms → DataFrame → API seconds regardless of server TZ
def test_binance_ms_round_trips_to_unix_seconds():
    from ai_trader.core.data.providers.binance import BinanceDataSource
    from ai_trader.web.services.market_data import df_to_bars, to_unix_seconds

    ms = 1704067200000  # 2024-01-01 00:00:00 UTC
    row = [ms, "40000", "41000", "39000", "40500", "12.5", ms + 86399999, "0", 0, "0", "0", "0"]
    df = BinanceDataSource()._parse_klines_data([row])
    assert to_unix_seconds(df.index[0]) == 1704067200
    assert df_to_bars(df)[0].time == 1704067200


# I1 — start > end must be a 422 before touching the data source
def test_start_after_end_is_422_without_calling_source(client, fake_data_source, monkeypatch):
    from ai_trader.web.services import market_data as m

    calls = []
    monkeypatch.setattr(m.get_data_source(), "get_historical_data", lambda *a, **k: calls.append(1))
    r = client.get("/api/market/klines", params={"symbol": "BTCUSDT", "interval": "1d", "start": "2024-03-31", "end": "2024-03-01"})
    assert r.status_code == 422 and "start" in r.json()["detail"]
    assert calls == []


# I2 — ranges ending today must refetch once the day changes
def test_cache_refreshes_for_ranges_ending_today(fake_data_source, monkeypatch):
    from ai_trader.web.services import market_data as m

    m.reset_data_source()
    m.fetch_klines.cache_clear()
    calls = []
    ds = m.get_data_source()
    orig = ds.get_historical_data
    monkeypatch.setattr(ds, "get_historical_data", lambda *a, **k: (calls.append(1), orig(*a, **k))[1])
    today = date(2024, 6, 1)
    monkeypatch.setattr(m, "_today", lambda: today)
    m.fetch_klines("BTCUSDT", "1d", "2024-01-01", "2024-06-01")
    m.fetch_klines("BTCUSDT", "1d", "2024-01-01", "2024-06-01")
    assert len(calls) == 1
    monkeypatch.setattr(m, "_today", lambda: date(2024, 6, 2))
    m.fetch_klines("BTCUSDT", "1d", "2024-01-01", "2024-06-01")
    assert len(calls) == 2
    # a range fully in the past is never refetched
    m.fetch_klines("BTCUSDT", "1d", "2024-01-01", "2024-03-01")
    m.fetch_klines("BTCUSDT", "1d", "2024-01-01", "2024-03-01")
    assert len(calls) == 3


# I3 — parameter bounds
BODY = {"data": {"symbol": "BTCUSDT", "interval": "1d", "start": "2024-01-01", "end": "2025-02-03"}}


@pytest.mark.parametrize(
    "patch",
    [
        {"indicators": {"rsi_period": 0}},
        {"indicators": {"kdj_d": 0}},
        {"indicators": {"sma_periods": [0]}},
        {"indicators": {"bb_std": 0}},
        {"signals": {"min_conditions": 0}},
        {"backtest": {"position_size": 2}},
        {"backtest": {"initial_capital": 0}},
        {"backtest": {"commission_rate": -0.1}},
    ],
)
def test_out_of_range_params_are_422(client, fake_data_source, patch):
    assert client.post("/api/backtest/run", json={**BODY, **patch}).status_code == 422


# I4 — symbols must report Binance outage instead of an empty list
def test_symbols_502_when_connect_fails(client, monkeypatch):
    from ai_trader.core.data.providers.binance import BinanceDataSource

    monkeypatch.setattr(BinanceDataSource, "connect", lambda self: False)
    r = client.get("/api/market/symbols")
    assert r.status_code == 502


# I7 — SPA catch-all must not escape dist and must 404 missing assets
def test_spa_does_not_serve_sibling_dirs_or_missing_assets(tmp_path: Path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<title>AI Trader</title>", encoding="utf-8")
    sibling = tmp_path / "dist-old"
    sibling.mkdir()
    (sibling / "secret.txt").write_text("SECRET", encoding="utf-8")
    client = TestClient(create_app(dist_dir=dist))
    assert client.get("/%2e%2e/dist-old/secret.txt").status_code == 404
    assert client.get("/../dist-old/secret.txt").status_code == 404
    assert client.get("/assets/missing.js").status_code == 404
    assert client.get("/favicon.ico").status_code == 404
    assert client.get("/analysis").status_code == 200
