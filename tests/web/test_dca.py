BODY = {"symbol": "BTCUSDT", "amount": 200, "day": 10, "start_date": "2024-01-01", "end_date": "2024-12-31"}


def test_dca_calculate(client, fake_data_source):
    r = client.post("/api/dca/calculate", json=BODY)
    body = r.json()
    assert r.status_code == 200
    assert body["investment_count"] == len(body["records"]) > 0
    assert abs(body["total_invested"] - 200 * body["investment_count"]) < 1e-6
    assert body["records"][0]["date"] == "2024-01-10"


def test_dca_validation_422(client, fake_data_source):
    assert client.post("/api/dca/calculate", json={**BODY, "amount": -1}).status_code == 422


def test_dca_binance_down_502(client, broken_data_source):
    assert client.post("/api/dca/calculate", json=BODY).status_code == 502
