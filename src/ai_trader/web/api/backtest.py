"""/api/backtest：策略回测。"""

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool

from ai_trader.web.schemas import BacktestRequest, BacktestResponse
from ai_trader.web.services.backtest import run_backtest

router = APIRouter(prefix="/api/backtest", tags=["backtest"])


@router.post("/run", response_model=BacktestResponse)
async def run(req: BacktestRequest) -> BacktestResponse:
    return await run_in_threadpool(run_backtest, req)
