"""Pydantic 请求/响应模型（全部 snake_case）。"""

from datetime import date
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

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
class AllocationIn(BaseModel):
    symbol: str
    weight: float = Field(gt=0)


class DCARequest(BaseModel):
    """新格式：frequency + allocations；兼容旧格式：symbol（单币种、每月）。"""

    frequency: Literal["daily", "monthly"] = "monthly"
    day: int = Field(default=10, ge=1, le=31)
    hour: Optional[int] = Field(default=None, ge=0, le=23)  # 北京时间小时；None = 日线收盘价
    amount: float = Field(gt=0)
    start_date: date
    end_date: Optional[date] = None
    symbol: Optional[str] = None
    allocations: List[AllocationIn] = Field(default_factory=list)

    @model_validator(mode="after")
    def _fill_allocations(self) -> "DCARequest":
        if not self.allocations:
            if not self.symbol:
                raise ValueError("either allocations or symbol is required")
            self.allocations = [AllocationIn(symbol=self.symbol, weight=1.0)]
        return self


class DCARecord(BaseModel):
    date: str
    price: float
    amount: float
    coins: float


class DCALeg(BaseModel):
    symbol: str
    weight: float
    total_invested: float
    total_coins: float
    current_price: float
    total_value: float
    profit: float
    profit_rate: float
    average_cost: float
    investment_count: int
    records: List[DCARecord]


class DCAPeriod(BaseModel):
    date: str
    amount: float


class DCAResponse(BaseModel):
    frequency: str
    invest_hour: Optional[int] = None
    amount: float
    start_date: str
    end_date: str
    investment_count: int
    total_invested: float
    total_value: float
    profit: float
    profit_rate: float
    legs: List[DCALeg]
    records: List[DCAPeriod]
    # 单币种时保留的旧字段（多币种为 None）
    symbol: Optional[str] = None
    total_coins: Optional[float] = None
    current_price: Optional[float] = None
    average_cost: Optional[float] = None


# ---- 技术分析 ----
class IndicatorParams(BaseModel):
    sma_periods: List[int] = Field(default=[5, 10, 20, 50, 200])
    macd_fast: int = Field(default=12, ge=1)
    macd_slow: int = Field(default=26, ge=1)
    macd_signal: int = Field(default=9, ge=1)
    rsi_period: int = Field(default=14, ge=1)
    kdj_k: int = Field(default=9, ge=1)
    kdj_d: int = Field(default=3, ge=1)
    kdj_j: int = Field(default=3, ge=1)
    bb_period: int = Field(default=20, ge=1)
    bb_std: float = Field(default=2.0, gt=0)

    @field_validator("sma_periods")
    @classmethod
    def _periods_positive(cls, v: List[int]) -> List[int]:
        if any(p < 1 for p in v):
            raise ValueError("sma_periods must all be >= 1")
        return v


class SignalParams(BaseModel):
    rsi_oversold: int = Field(default=30, ge=0, le=100)
    rsi_overbought: int = Field(default=70, ge=0, le=100)
    trend_required: bool = True
    macd_required: bool = True
    rsi_required: bool = True
    kdj_required: bool = True
    bb_required: bool = True
    pattern_required: bool = True
    volume_required: bool = True
    combination: Literal["all", "min"] = "all"
    min_conditions: int = Field(default=2, ge=1)

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
    initial_capital: float = Field(default=100000, gt=0)
    position_size: float = Field(default=0.1, gt=0, le=1)
    commission_rate: float = Field(default=0.001, ge=0)
    slippage_rate: float = Field(default=0.0005, ge=0)


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
