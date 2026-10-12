"""/api/analysis：指标、形态、信号。"""

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool

from ai_trader.web.schemas import AnalysisRequest, AnalysisResponse
from ai_trader.web.services.analysis import run_analysis

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


@router.post("/run", response_model=AnalysisResponse)
async def run(req: AnalysisRequest) -> AnalysisResponse:
    return await run_in_threadpool(run_analysis, req)
