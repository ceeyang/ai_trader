BASE = {"amount": 1000, "start_date": "2024-01-01", "end_date": "2024-03-31"}


def test_legacy_single_symbol_body_still_works(client, fake_data_source):
    r = client.post("/api/dca/calculate", json={"symbol": "BTCUSDT", "amount": 200, "day": 10, "start_date": "2024-01-01", "end_date": "2024-03-31"})
    b = r.json()
    assert r.status_code == 200
    assert b["frequency"] == "monthly" and b["investment_count"] == 3
    assert b["symbol"] == "BTCUSDT" and len(b["records"]) == 3  # legacy top-level fields kept
    assert b["legs"][0]["symbol"] == "BTCUSDT" and b["legs"][0]["weight"] == 1.0


def test_daily_mode(client, fake_data_source):
    r = client.post("/api/dca/calculate", json={**BASE, "frequency": "daily", "allocations": [{"symbol": "BTCUSDT", "weight": 1}]})
    assert r.status_code == 200 and r.json()["investment_count"] == 91  # 2024 is a leap year


def test_portfolio_mode_normalizes_weights(client, fake_data_source):
    r = client.post("/api/dca/calculate", json={**BASE, "frequency": "monthly", "day": 10,
                                                "allocations": [{"symbol": "BTCUSDT", "weight": 60}, {"symbol": "ETHUSDT", "weight": 40}]})
    b = r.json()
    assert r.status_code == 200
    assert [l["weight"] for l in b["legs"]] == [0.6, 0.4]
    assert abs(b["total_invested"] - 3000) < 1e-6
    assert b["records"][0]["date"] == "2024-01-10"


def test_bad_weights_422(client, fake_data_source):
    assert client.post("/api/dca/calculate", json={**BASE, "frequency": "monthly", "allocations": [{"symbol": "BTCUSDT", "weight": 0}]}).status_code == 422
    assert client.post("/api/dca/calculate", json={**BASE, "frequency": "monthly", "allocations": []}).status_code == 422
    assert client.post("/api/dca/calculate", json={**BASE, "frequency": "weekly", "allocations": [{"symbol": "BTCUSDT", "weight": 1}]}).status_code == 422


def test_missing_symbol_and_allocations_422(client, fake_data_source):
    assert client.post("/api/dca/calculate", json={**BASE, "frequency": "daily"}).status_code == 422


def test_hour_is_passed_through_and_echoed(client, fake_data_source):
    r = client.post("/api/dca/calculate", json={**BASE, "frequency": "daily", "hour": 20, "allocations": [{"symbol": "BTCUSDT", "weight": 1}]})
    assert r.status_code == 200 and r.json()["invest_hour"] == 20
    assert r.json()["investment_count"] == 91


def test_no_hour_echoes_null(client, fake_data_source):
    r = client.post("/api/dca/calculate", json={**BASE, "frequency": "daily", "allocations": [{"symbol": "BTCUSDT", "weight": 1}]})
    assert r.status_code == 200 and r.json()["invest_hour"] is None


def test_hour_out_of_range_422(client, fake_data_source):
    assert client.post("/api/dca/calculate", json={**BASE, "frequency": "daily", "hour": 24, "allocations": [{"symbol": "BTCUSDT", "weight": 1}]}).status_code == 422
