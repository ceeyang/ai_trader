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


# ---- 定投时间（北京时间小时，走 1h K 线）----
from datetime import timedelta, timezone  # noqa: E402

BEIJING = timezone(timedelta(hours=8))


def _local_naive_at_beijing(date_str: str, hour: int) -> pd.Timestamp:
    """北京时间 date hour:00 对应的本机本地 naive 时间（与数据源索引同一约定）。"""
    bj = datetime.fromisoformat(date_str).replace(hour=hour, tzinfo=BEIJING)
    return pd.Timestamp(bj.astimezone().replace(tzinfo=None))


def test_daily_with_hour_uses_open_of_that_hour(fake_data_source):
    ds = _ds()
    plan = DCAPlan("daily", 10, datetime(2024, 2, 1), datetime(2024, 2, 5), [Allocation("BTCUSDT", 1)], invest_hour=20)
    r = run_dca_plan(plan, ds)
    recs = r["legs"][0]["records"]
    assert [x["date"] for x in recs] == ["2024-02-01", "2024-02-02", "2024-02-03", "2024-02-04", "2024-02-05"]
    hourly = ds.get_historical_data("BTCUSDT", "1h", datetime(2024, 1, 30), datetime(2024, 2, 8))
    for x in recs:
        assert x["price"] == pytest.approx(float(hourly.loc[_local_naive_at_beijing(x["date"], 20), "open"]))


def test_hour_before_8_maps_to_previous_utc_day(fake_data_source):
    ds = _ds()
    plan = DCAPlan("daily", 10, datetime(2024, 2, 1), datetime(2024, 2, 2), [Allocation("BTCUSDT", 1)], invest_hour=3)
    r = run_dca_plan(plan, ds)
    recs = r["legs"][0]["records"]
    assert [x["date"] for x in recs] == ["2024-02-01", "2024-02-02"]
    hourly = ds.get_historical_data("BTCUSDT", "1h", datetime(2024, 1, 30), datetime(2024, 2, 8))
    assert recs[0]["price"] == pytest.approx(float(hourly.loc[_local_naive_at_beijing("2024-02-01", 3), "open"]))


def test_monthly_with_hour(fake_data_source):
    plan = DCAPlan("monthly", 100, datetime(2024, 1, 1), datetime(2024, 3, 31), [Allocation("BTCUSDT", 1)], invest_day=15, invest_hour=9)
    r = run_dca_plan(plan, _ds())
    assert [x["date"] for x in r["legs"][0]["records"]] == ["2024-01-15", "2024-02-15", "2024-03-15"]
    assert r["invest_hour"] == 9


def test_hourly_range_is_fetched_in_small_chunks(fake_data_source, monkeypatch):
    ds = _ds()
    calls = []
    orig = ds.get_historical_data
    monkeypatch.setattr(ds, "get_historical_data", lambda *a, **k: (calls.append((k["interval"], k["start_time"], k["end_time"])), orig(*a, **k))[1])
    plan = DCAPlan("daily", 1, datetime(2024, 1, 1), datetime(2024, 6, 30), [Allocation("BTCUSDT", 1)], invest_hour=12)
    r = run_dca_plan(plan, ds)
    assert all(i == "1h" and (e - s).days <= 40 for i, s, e in calls) and len(calls) >= 4
    assert r["investment_count"] == 182  # 2024-01-01..2024-06-30，分段边界不能丢天


def test_no_hour_keeps_daily_close_behaviour(fake_data_source):
    plan = DCAPlan("daily", 10, datetime(2024, 2, 1), datetime(2024, 2, 3), [Allocation("BTCUSDT", 1)])
    r = run_dca_plan(plan, _ds())
    assert r["invest_hour"] is None
    assert r["legs"][0]["records"][0]["price"] == pytest.approx(float(fake_data_source.loc["2024-02-01", "close"]))


def test_invalid_hour_rejected(fake_data_source):
    plan = DCAPlan("daily", 10, datetime(2024, 2, 1), datetime(2024, 2, 3), [Allocation("BTCUSDT", 1)], invest_hour=24)
    with pytest.raises(ValueError):
        run_dca_plan(plan, _ds())
