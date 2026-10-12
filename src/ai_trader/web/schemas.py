"""Pydantic 请求/响应模型（全部 snake_case）。"""

from datetime import date
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from ai_trader.core.analysis.signals import SignalConfig


class Bar(BaseModel):
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float


class KlinesResponse(BaseModel):
    bars: List[Bar]


class SymbolsResponse(BaseModel):
    symbols: List[str]


class IntervalsResponse(BaseModel):
    intervals: List[str]


# ---- DCA ----
class DCARequest(BaseModel):
    symbol: str
    amount: float = Field(gt=0)
    day: int = Field(ge=1, le=31)
    start_date: date
    end_date: Optional[date] = None


class DCARecord(BaseModel):
    date: str
    price: float
    amount: float
    coins: float


class DCAResponse(BaseModel):
    symbol: str
    total_invested: float
    total_coins: float
    current_price: float
    total_value: float
    profit: float
    profit_rate: float
    average_cost: float
    investment_count: int
    records: List[DCARecord]


# ---- 技术分析 ----
class IndicatorParams(BaseModel):
    sma_periods: List[int] = [5, 10, 20, 50, 200]
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    rsi_period: int = 14
    kdj_k: int = 9
    kdj_d: int = 3
    kdj_j: int = 3
    bb_period: int = 20
    bb_std: float = 2.0


class SignalParams(BaseModel):
    rsi_oversold: int = 30
    rsi_overbought: int = 70
    trend_required: bool = True
    macd_required: bool = True
    rsi_required: bool = True
    kdj_required: bool = True
    bb_required: bool = True
    pattern_required: bool = True
    volume_required: bool = True
    combination: Literal["all", "min"] = "all"
    min_conditions: int = 2

    def to_config(self) -> SignalConfig:
        return SignalConfig(**self.model_dump())


class DataRange(BaseModel):
    symbol: str
    interval: str
    start: date
    end: date


class AnalysisRequest(BaseModel):
    data: DataRange
    indicators: IndicatorParams = IndicatorParams()
    signals: SignalParams = SignalParams()


class EffectivenessStat(BaseModel):
    frequency: float
    avg_price_change_1d: float
    positive_rate: float


class AnalysisResponse(BaseModel):
    indicators: Dict[str, List[Optional[float]]]
    patterns: Dict[str, List[int]]
    entry_signals: List[int]
    exit_signals: List[int]
    effectiveness: Dict[str, EffectivenessStat]


# ---- 回测 ----
class BacktestParams(BaseModel):
    initial_capital: float = 100000
    position_size: float = 0.1
    commission_rate: float = 0.001
    slippage_rate: float = 0.0005


class BacktestRequest(AnalysisRequest):
    backtest: BacktestParams = BacktestParams()


class TradeOut(BaseModel):
    entry_time: int
    exit_time: int
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    pnl_percent: float
    duration: int
    signal_strength: float


class BacktestResponse(BaseModel):
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: Optional[float]
    total_pnl: float
    total_return: float
    max_drawdown: float
    sharpe_ratio: Optional[float]
    avg_trade_duration: Optional[float]
    trades: List[TradeOut]


# ---- 参数预设 ----
class AnalysisPreset(BaseModel):
    indicators: IndicatorParams = IndicatorParams()
    signals: SignalParams = SignalParams()
    backtest: BacktestParams = BacktestParams()
