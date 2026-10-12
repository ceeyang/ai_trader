"""分析参数预设：data/analysis_config.json（目录可用 AI_TRADER_DATA_DIR 覆盖）。"""

import os
from pathlib import Path

from ai_trader.web.schemas import AnalysisPreset


def preset_path() -> Path:
    return Path(os.environ.get("AI_TRADER_DATA_DIR", "data")) / "analysis_config.json"


def load_preset() -> AnalysisPreset:
    path = preset_path()
    if not path.exists():
        return AnalysisPreset()
    return AnalysisPreset.model_validate_json(path.read_text(encoding="utf-8"))


def save_preset(preset: AnalysisPreset) -> None:
    path = preset_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(preset.model_dump_json(indent=2), encoding="utf-8")
