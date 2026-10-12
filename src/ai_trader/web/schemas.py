"""Pydantic 请求/响应模型（全部 snake_case）。"""

from typing import List

from pydantic import BaseModel


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
