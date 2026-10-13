"""/api/dca：定投收益计算（每日/每月，单币种或组合）。"""

from datetime import datetime, time

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool

from ai_trader.strategies.dca.plan import Allocation, DCAPlan, run_dca_plan
from ai_trader.web.schemas import DCARequest, DCAResponse
from ai_trader.web.services import market_data

router = APIRouter(prefix="/api/dca", tags=["dca"])


def _run(req: DCARequest) -> DCAResponse:
    plan = DCAPlan(
        frequency=req.frequency,
        amount=req.amount,
        start=datetime.combine(req.start_date, time.min),
        end=datetime.combine(req.end_date, time.min) if req.end_date else datetime.now(),
        allocations=[Allocation(a.symbol, a.weight) for a in req.allocations],
        invest_day=req.day,
    )
    result = run_dca_plan(plan, market_data.ensure_connected())
    if len(result["legs"]) == 1:
        leg = result["legs"][0]
        result.update(symbol=leg["symbol"], total_coins=leg["total_coins"],
                      current_price=leg["current_price"], average_cost=leg["average_cost"])
    return DCAResponse(**result)


@router.post("/calculate", response_model=DCAResponse)
async def calculate(req: DCARequest) -> DCAResponse:
    return await run_in_threadpool(_run, req)
