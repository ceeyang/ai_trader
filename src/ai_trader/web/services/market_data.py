"""币安数据源封装：单例连接、K 线 LRU 缓存、DataFrame → JSON 转换。"""

import math
from datetime import datetime
from functools import lru_cache
from typing import List, Optional

import pandas as pd
import requests

from ai_trader.core.data.providers.binance import BinanceDataSource
from ai_trader.web.schemas import Bar

_data_source: Optional[BinanceDataSource] = None


def get_data_source() -> BinanceDataSource:
    """模块级单例，首次调用时 connect()。"""
    global _data_source
    if _data_source is None:
        ds = BinanceDataSource()
        ds.connect()
        _data_source = ds
    return _data_source


def reset_data_source() -> None:
    """测试用：丢弃单例。"""
    global _data_source
    _data_source = None


def _parse_date(value: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"invalid date '{value}', expected YYYY-MM-DD") from exc


@lru_cache(maxsize=32)
def fetch_klines(symbol: str, interval: str, start: str, end: str) -> pd.DataFrame:
    """拉取并缓存 K 线。币安不可达 → ConnectionError；空结果 → ValueError。"""
    start_dt, end_dt = _parse_date(start), _parse_date(end)
    ds = get_data_source()
    if not ds.is_connected and not ds.connect():
        raise ConnectionError("binance unreachable")
    try:
        df = ds.get_historical_data(symbol=symbol, interval=interval, start_time=start_dt, end_time=end_dt)
    except requests.exceptions.RequestException as exc:
        raise ConnectionError(f"binance request failed: {exc}") from exc
    if df is None or len(df) == 0:
        raise ValueError(f"no data for {symbol} {interval} {start}..{end}")
    return df


def df_to_bars(df: pd.DataFrame) -> List[Bar]:
    return [
        Bar(
            time=int(ts.timestamp()),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
        )
        for ts, row in df.iterrows()
    ]


def nan_to_none(series: pd.Series) -> List[Optional[float]]:
    return [None if (v is None or (isinstance(v, float) and math.isnan(v))) else float(v) for v in series.tolist()]
