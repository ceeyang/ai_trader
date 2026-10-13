"""定投计划：每日/每月频率、多币种按权重分配、按区间拉取日线。

与旧的 ``get_dca_investment_dates`` 不同，这里严格按 start/end 区间取数据，
超过 1000 天的区间分段拉取后拼接。
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List

import pandas as pd

from ai_trader.core.base.data_source import BaseDataSource

FREQUENCIES = ("daily", "monthly")
CHUNK_DAYS = 900  # 币安单次最多 1000 根


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


def fetch_daily_range(data_source: BaseDataSource, symbol: str, start: datetime, end: datetime) -> pd.DataFrame:
    """按 ≤900 天分段拉取日线并拼接，去重排序。"""
    frames = []
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=CHUNK_DAYS), end)
        df = data_source.get_historical_data(symbol=symbol, interval="1d", start_time=cursor, end_time=chunk_end)
        if df is not None and len(df):
            frames.append(df)
        cursor = chunk_end + timedelta(days=1)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames)
    return out[~out.index.duplicated(keep="first")].sort_index()


def run_dca_plan(plan: DCAPlan, data_source: BaseDataSource) -> Dict[str, Any]:
    allocations = normalize_weights(plan.allocations)
    legs: List[Dict[str, Any]] = []
    period_totals: Dict[str, float] = {}

    for alloc in allocations:
        df = fetch_daily_range(data_source, alloc.symbol, plan.start, plan.end)
        if df.empty:
            raise ValueError(f"no data for {alloc.symbol} in {plan.start:%Y-%m-%d}..{plan.end:%Y-%m-%d}")
        dates = select_investment_dates(df.index, plan.frequency, plan.invest_day)
        per_period = plan.amount * alloc.weight
        records = []
        total_coins = 0.0
        for ts in dates:
            price = float(df.loc[ts, "close"])
            coins = per_period / price
            total_coins += coins
            date_str = ts.strftime("%Y-%m-%d")
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
