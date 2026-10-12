KL = {"symbol": "BTCUSDT", "interval": "1d", "start": "2024-03-01", "end": "2024-03-31"}


def test_symbols(client, fake_data_source):
    assert client.get("/api/market/symbols").json() == {"symbols": ["BTCUSDT", "ETHUSDT"]}


def test_intervals(client, fake_data_source):
    assert "1d" in client.get("/api/market/intervals").json()["intervals"]


def test_klines_ok(client, fake_data_source):
    r = client.get("/api/market/klines", params=KL)
    assert r.status_code == 200 and len(r.json()["bars"]) == 31
    assert set(r.json()["bars"][0]) == {"time", "open", "high", "low", "close", "volume"}


def test_klines_bad_date_422(client, fake_data_source):
    assert client.get("/api/market/klines", params={**KL, "start": "bad"}).status_code == 422


def test_klines_empty_range_422(client, fake_data_source):
    r = client.get("/api/market/klines", params={**KL, "start": "2030-01-01", "end": "2030-01-02"})
    assert r.status_code == 422 and "no data" in r.json()["detail"]


def test_klines_binance_down_502(client, broken_data_source):
    assert client.get("/api/market/klines", params=KL).status_code == 502
