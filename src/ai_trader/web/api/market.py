"""/api/market：交易对、周期、K 线。"""

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool

from ai_trader.web.schemas import IntervalsResponse, KlinesResponse, SymbolsResponse
from ai_trader.web.services import market_data

router = APIRouter(prefix="/api/market", tags=["market"])


@router.get("/symbols", response_model=SymbolsResponse)
async def symbols(mainstream_only: bool = True) -> SymbolsResponse:
    ds = market_data.get_data_source()
    result = await run_in_threadpool(ds.get_available_symbols, mainstream_only)
    return SymbolsResponse(symbols=result)


@router.get("/intervals", response_model=IntervalsResponse)
def intervals() -> IntervalsResponse:
    return IntervalsResponse(intervals=market_data.get_data_source().get_supported_intervals())


@router.get("/klines", response_model=KlinesResponse)
async def klines(symbol: str, interval: str, start: str, end: str) -> KlinesResponse:
    df = await run_in_threadpool(market_data.fetch_klines, symbol, interval, start, end)
    return KlinesResponse(bars=market_data.df_to_bars(df))
