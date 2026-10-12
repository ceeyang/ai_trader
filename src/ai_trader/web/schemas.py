"""Pydantic 请求/响应模型（全部 snake_case）。"""

from datetime import date
from typing import List, Optional

from pydantic import BaseModel, Field


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
