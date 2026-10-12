"""/api/config：分析参数预设。"""

from fastapi import APIRouter

from ai_trader.web.schemas import AnalysisPreset
from ai_trader.web.services.presets import load_preset, save_preset

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("/analysis", response_model=AnalysisPreset)
def get_analysis_preset() -> AnalysisPreset:
    return load_preset()


@router.put("/analysis", response_model=AnalysisPreset)
def put_analysis_preset(preset: AnalysisPreset) -> AnalysisPreset:
    save_preset(preset)
    return load_preset()
