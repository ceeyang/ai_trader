"""/api/dca：定投收益计算。"""

from datetime import datetime, time

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool

from ai_trader.strategies.dca.dca_strategy import DCAStrategy
from ai_trader.web.schemas import DCARequest, DCAResponse

router = APIRouter(prefix="/api/dca", tags=["dca"])


@router.post("/calculate", response_model=DCAResponse)
async def calculate(req: DCARequest) -> DCAResponse:
    start = datetime.combine(req.start_date, time.min)
    end = datetime.combine(req.end_date, time.min) if req.end_date else datetime.now()
    strategy = DCAStrategy(
        symbol=req.symbol,
        invest_amount=req.amount,
        invest_day=req.day,
        start_date=start,
        end_date=end,
    )
    result = await run_in_threadpool(strategy.execute_dca)
    return DCAResponse(**result)
