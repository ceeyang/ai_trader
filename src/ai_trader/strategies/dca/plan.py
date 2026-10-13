"""定投计划：每日/每月频率、多币种按权重分配、按区间拉取日线。

与旧的 ``get_dca_investment_dates`` 不同，这里严格按 start/end 区间取数据，
超过 1000 天的区间分段拉取后拼接。
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pandas as pd

from ai_trader.core.base.data_source import BaseDataSource

FREQUENCIES = ("daily", "monthly")
CHUNK_DAYS = {"1d": 900, "1h": 40}  # 币安单次最多 1000 根：日线按天、小时线按 40 天（960 根）分段
BEIJING = timezone(timedelta(hours=8))


@dataclass
class Allocation:
    symbol: str
    weight: float


@dataclass
class DCAPlan:
    frequency: str
    amount: float  # 每期总额
    start: datetime
    end: datetime
    allocations: List[Allocation] = field(default_factory=list)
    invest_day: int = 10  # 仅 monthly
    invest_hour: Optional[int] = None  # 北京时间小时 0-23；None = 用日线收盘价（旧行为）


def select_investment_dates(index: pd.DatetimeIndex, frequency: str, invest_day: int = 10) -> pd.DatetimeIndex:
    if frequency == "daily":
        return index
    if frequency == "monthly":
        return index[index.day == invest_day]
    raise ValueError(f"unsupported frequency '{frequency}', expected one of {FREQUENCIES}")


def normalize_weights(allocations: List[Allocation]) -> List[Allocation]:
    if not allocations:
        raise ValueError("allocations must not be empty")
    if any(a.weight <= 0 for a in allocations):
        raise ValueError("all weights must be positive")
    total = sum(a.weight for a in allocations)
    return [Allocation(a.symbol, a.weight / total) for a in allocations]


def fetch_range(data_source: BaseDataSource, symbol: str, start: datetime, end: datetime, interval: str = "1d") -> pd.DataFrame:
    """按区间分段拉取 K 线并拼接，去重排序（日线 ≤900 天/段，小时线 ≤40 天/段）。"""
    frames = []
    cursor = start
    step = CHUNK_DAYS[interval]
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=step), end)
        df = data_source.get_historical_data(symbol=symbol, interval=interval, start_time=cursor, end_time=chunk_end)
        if df is not None and len(df):
            frames.append(df)
        cursor = chunk_end + (timedelta(hours=1) if interval == "1h" else timedelta(days=1))
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames)
    return out[~out.index.duplicated(keep="first")].sort_index()


def fetch_daily_range(data_source: BaseDataSource, symbol: str, start: datetime, end: datetime) -> pd.DataFrame:
    return fetch_range(data_source, symbol, start, end, "1d")


def _beijing_index(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """数据源索引是本机本地时间的 naive 时间戳；转成北京时间（带时区）。"""
    epochs = [ts.to_pydatetime().timestamp() for ts in index]
    return pd.to_datetime(epochs, unit="s", utc=True).tz_convert(BEIJING)


def select_hourly_bars(df: pd.DataFrame, plan: DCAPlan) -> List[tuple]:
    """返回 [(日期标签 YYYY-MM-DD, 原索引时间戳)]：每个北京日期取 invest_hour 整点那根 1h K 线。"""
    bj = _beijing_index(df.index)
    mask = bj.hour == plan.invest_hour
    if plan.frequency == "monthly":
        mask &= bj.day == plan.invest_day
    start_d, end_d = plan.start.date(), plan.end.date()
    picked: Dict[str, pd.Timestamp] = {}
    for ts_local, ts_bj in zip(df.index[mask], bj[mask]):
        if start_d <= ts_bj.date() <= end_d:
            picked.setdefault(ts_bj.strftime("%Y-%m-%d"), ts_local)
    return sorted(picked.items())


def run_dca_plan(plan: DCAPlan, data_source: BaseDataSource) -> Dict[str, Any]:
    allocations = normalize_weights(plan.allocations)
    legs: List[Dict[str, Any]] = []
    period_totals: Dict[str, float] = {}

    if plan.frequency not in FREQUENCIES:
        raise ValueError(f"unsupported frequency '{plan.frequency}', expected one of {FREQUENCIES}")
    if plan.invest_hour is not None and not 0 <= plan.invest_hour <= 23:
        raise ValueError("invest_hour must be between 0 and 23")

    for alloc in allocations:
        if plan.invest_hour is None:
            df = fetch_daily_range(data_source, alloc.symbol, plan.start, plan.end)
            if df.empty:
                raise ValueError(f"no data for {alloc.symbol} in {plan.start:%Y-%m-%d}..{plan.end:%Y-%m-%d}")
            picks = [(ts.strftime("%Y-%m-%d"), ts, "close") for ts in select_investment_dates(df.index, plan.frequency, plan.invest_day)]
        else:
            # 多拉一天，保证结束日期当天的目标小时也在数据里；按北京日期过滤
            df = fetch_range(data_source, alloc.symbol, plan.start - timedelta(days=1), plan.end + timedelta(days=1), "1h")
            if df.empty:
                raise ValueError(f"no data for {alloc.symbol} in {plan.start:%Y-%m-%d}..{plan.end:%Y-%m-%d}")
            picks = [(label, ts, "open") for label, ts in select_hourly_bars(df, plan)]
        per_period = plan.amount * alloc.weight
        records = []
        total_coins = 0.0
        for date_str, ts, col in picks:
            price = float(df.loc[ts, col])
            coins = per_period / price
            total_coins += coins
            records.append({"date": date_str, "price": price, "amount": per_period, "coins": coins})
            period_totals[date_str] = period_totals.get(date_str, 0.0) + per_period
        total_invested = per_period * len(records)
        current_price = float(data_source.get_current_price(alloc.symbol))
        total_value = total_coins * current_price
        profit = total_value - total_invested
        legs.append({
            "symbol": alloc.symbol,
            "weight": alloc.weight,
            "total_invested": total_invested,
            "total_coins": total_coins,
            "current_price": current_price,
            "total_value": total_value,
            "profit": profit,
            "profit_rate": (profit / total_invested * 100) if total_invested else 0.0,
            "average_cost": (total_invested / total_coins) if total_coins else 0.0,
            "investment_count": len(records),
            "records": records,
        })

    total_invested = sum(l["total_invested"] for l in legs)
    total_value = sum(l["total_value"] for l in legs)
    profit = total_value - total_invested
    return {
        "frequency": plan.frequency,
        "invest_hour": plan.invest_hour,
        "amount": plan.amount,
        "start_date": plan.start.strftime("%Y-%m-%d"),
        "end_date": plan.end.strftime("%Y-%m-%d"),
        "investment_count": len(period_totals),
        "total_invested": total_invested,
        "total_value": total_value,
        "profit": profit,
        "profit_rate": (profit / total_invested * 100) if total_invested else 0.0,
        "legs": legs,
        "records": [{"date": d, "amount": a} for d, a in sorted(period_totals.items())],
    }
