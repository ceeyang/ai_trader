from datetime import datetime

import pandas as pd
import pytest

from ai_trader.strategies.dca.plan import Allocation, DCAPlan, normalize_weights, run_dca_plan, select_investment_dates


def _ds():
    from ai_trader.core.data.providers.binance import BinanceDataSource

    ds = BinanceDataSource()
    ds.connect()
    return ds


# ---- 日期选择 ----
def test_daily_selects_every_bar(sample_ohlcv):
    idx = sample_ohlcv.index[:40]
    assert select_investment_dates(idx, "daily").equals(idx)


def test_monthly_selects_invest_day_and_skips_missing_31st(sample_ohlcv):
    idx = sample_ohlcv.index  # 2024-01-01 .. 2025-02-03 (400 days)
    chosen = select_investment_dates(idx, "monthly", invest_day=31)
    # Jan, Mar, May, Jul, Aug, Oct, Dec 2024 and Jan 2025 have a 31st = 8; Feb/Apr/Jun/Sep/Nov skipped
    assert len(chosen) == 8 and all(d.day == 31 for d in chosen)


def test_unknown_frequency_rejected(sample_ohlcv):
    with pytest.raises(ValueError):
        select_investment_dates(sample_ohlcv.index, "weekly")


# ---- 权重 ----
def test_normalize_weights():
    out = normalize_weights([Allocation("BTCUSDT", 3), Allocation("ETHUSDT", 1)])
    assert [a.weight for a in out] == [0.75, 0.25]


@pytest.mark.parametrize("allocs", [[], [Allocation("BTCUSDT", 0)], [Allocation("BTCUSDT", -1), Allocation("ETHUSDT", 2)]])
def test_invalid_weights_rejected(allocs):
    with pytest.raises(ValueError):
        normalize_weights(allocs)


# ---- 执行 ----
def test_single_monthly_respects_date_range(fake_data_source):
    """回归：旧实现忽略 start/end，只拉最近 N 根。"""
    plan = DCAPlan("monthly", 200, datetime(2024, 3, 1), datetime(2024, 6, 30), [Allocation("BTCUSDT", 1)], invest_day=10)
    r = run_dca_plan(plan, _ds())
    assert [rec["date"] for rec in r["legs"][0]["records"]] == ["2024-03-10", "2024-04-10", "2024-05-10", "2024-06-10"]
    assert r["investment_count"] == 4 and r["total_invested"] == pytest.approx(800)


def test_daily_counts_every_day(fake_data_source):
    plan = DCAPlan("daily", 10, datetime(2024, 2, 1), datetime(2024, 2, 29), [Allocation("BTCUSDT", 1)])
    r = run_dca_plan(plan, _ds())
    assert r["investment_count"] == 29 and r["total_invested"] == pytest.approx(290)


def test_portfolio_splits_amount_by_weight_and_sums(fake_data_source):
    plan = DCAPlan("monthly", 1000, datetime(2024, 1, 1), datetime(2024, 3, 31),
                   [Allocation("BTCUSDT", 60), Allocation("ETHUSDT", 40)], invest_day=10)
    r = run_dca_plan(plan, _ds())
    btc, eth = r["legs"]
    assert (btc["weight"], eth["weight"]) == (0.6, 0.4)
    assert btc["total_invested"] == pytest.approx(1800) and eth["total_invested"] == pytest.approx(1200)
    assert r["total_invested"] == pytest.approx(3000)
    assert r["total_value"] == pytest.approx(btc["total_value"] + eth["total_value"])
    assert r["profit"] == pytest.approx(r["total_value"] - r["total_invested"])
    assert r["records"][0] == {"date": "2024-01-10", "amount": pytest.approx(1000)}
    # coins bought = amount / close on that day
    close = fake_data_source.loc["2024-01-10", "close"]
    assert btc["records"][0]["coins"] == pytest.approx(600 / close)


def test_long_range_is_fetched_in_chunks(fake_data_source, monkeypatch):
    ds = _ds()
    calls = []
    orig = ds.get_historical_data
    monkeypatch.setattr(ds, "get_historical_data", lambda *a, **k: (calls.append((k["start_time"], k["end_time"])), orig(*a, **k))[1])
    plan = DCAPlan("daily", 1, datetime(2020, 1, 1), datetime(2024, 6, 1), [Allocation("BTCUSDT", 1)])
    run_dca_plan(plan, ds)
    assert len(calls) >= 2 and all((e - s).days <= 900 for s, e in calls)


def test_no_bars_in_range_raises(fake_data_source):
    plan = DCAPlan("daily", 1, datetime(2030, 1, 1), datetime(2030, 1, 5), [Allocation("BTCUSDT", 1)])
    with pytest.raises(ValueError):
        run_dca_plan(plan, _ds())
