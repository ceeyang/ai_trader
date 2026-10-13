"""共享测试夹具：确定性合成 K 线 + 假币安数据源（测试不联网）。"""

from datetime import datetime
from typing import Any, Dict, List

import numpy as np
import pandas as pd
import pytest

from ai_trader.core.data.providers import binance as binance_module


def make_sample_ohlcv(
    n: int = 400, seed: int = 42, start: str = "2024-01-01", freq: str = "D"
) -> pd.DataFrame:
    """种子随机游走生成的 OHLCV，起点 40000，日波动 2%。"""
    rng = np.random.default_rng(seed)
    index = pd.date_range(start=start, periods=n, freq=freq)
    returns = rng.normal(0.0, 0.02, size=n)
    close = 40000.0 * np.exp(np.cumsum(returns))
    open_ = np.concatenate([[40000.0], close[:-1]]) * (1 + rng.normal(0, 0.003, size=n))
    body_hi = np.maximum(open_, close)
    body_lo = np.minimum(open_, close)
    high = body_hi * (1 + np.abs(rng.normal(0, 0.005, size=n)))
    low = body_lo * (1 - np.abs(rng.normal(0, 0.005, size=n)))
    volume = rng.uniform(1000.0, 5000.0, size=n)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=index,
    )


@pytest.fixture
def sample_ohlcv() -> pd.DataFrame:
    return make_sample_ohlcv()


def _install_fake(monkeypatch: pytest.MonkeyPatch, df: pd.DataFrame) -> None:
    cls = binance_module.BinanceDataSource
    hourly = make_sample_ohlcv(n=len(df) * 24, seed=7, start=str(df.index[0].date()), freq="h")

    def connect(self: Any) -> bool:
        self.is_connected = True
        return True

    def disconnect(self: Any) -> None:
        self.is_connected = False

    def get_historical_data(
        self: Any, symbol: str, interval: str, start_time: datetime, end_time: datetime
    ) -> pd.DataFrame:
        src = hourly if interval == "1h" else df
        return src.loc[(src.index >= start_time) & (src.index <= end_time)].copy()

    def get_available_symbols(self: Any, mainstream_only: bool = True) -> List[str]:
        return ["BTCUSDT", "ETHUSDT"]

    def get_current_price(self: Any, symbol: str) -> float:
        return float(df["close"].iloc[-1])

    def get_dca_investment_dates(
        self: Any, symbol: str, start_date: datetime, end_date: datetime, invest_day: int
    ) -> List[Dict[str, Any]]:
        rows = df.loc[(df.index >= start_date) & (df.index <= end_date)]
        rows = rows[rows.index.day == invest_day]
        return [
            {"date": ts.strftime("%Y-%m-%d"), "datetime": ts.to_pydatetime(), "close": float(r["close"])}
            for ts, r in rows.iterrows()
        ]

    monkeypatch.setattr(cls, "connect", connect)
    monkeypatch.setattr(cls, "disconnect", disconnect)
    monkeypatch.setattr(cls, "get_historical_data", get_historical_data)
    monkeypatch.setattr(cls, "get_available_symbols", get_available_symbols)
    monkeypatch.setattr(cls, "get_current_price", get_current_price)
    monkeypatch.setattr(cls, "get_dca_investment_dates", get_dca_investment_dates)


@pytest.fixture
def fake_data_source(monkeypatch: pytest.MonkeyPatch) -> pd.DataFrame:
    df = make_sample_ohlcv()
    _install_fake(monkeypatch, df)
    return df


@pytest.fixture
def broken_data_source(monkeypatch: pytest.MonkeyPatch) -> None:
    cls = binance_module.BinanceDataSource

    def connect(self: Any) -> bool:
        self.is_connected = True
        return True

    def boom(self: Any, *args: Any, **kwargs: Any) -> Any:
        raise ConnectionError("binance unreachable")

    monkeypatch.setattr(cls, "connect", connect)
    monkeypatch.setattr(cls, "get_historical_data", boom)
    monkeypatch.setattr(cls, "get_dca_investment_dates", boom)
    monkeypatch.setattr(cls, "get_available_symbols", boom)
