"""技术分析编排：指标、形态、信号、信号有效性。"""

from typing import Dict, List, Optional, Tuple

import pandas as pd

from ai_trader.core.analysis.backtest import BacktestEngine
from ai_trader.core.analysis.indicators import TechnicalIndicators
from ai_trader.core.analysis.patterns import CandlestickPatterns
from ai_trader.core.analysis.signals import SignalConfig, SignalDetector
from ai_trader.web.schemas import AnalysisRequest, AnalysisResponse, EffectivenessStat, IndicatorParams
from ai_trader.web.services.market_data import fetch_klines, nan_to_none, to_unix_seconds


def _true_times(series: pd.Series) -> List[int]:
    return [to_unix_seconds(ts) for ts in series.index[series.astype(bool)]]


def compute_indicators(df: pd.DataFrame, params: IndicatorParams) -> Dict[str, List[Optional[float]]]:
    """键名沿用 Tkinter 版：sma_{p}、macd_dif/dea/hist、rsi、kdj_k/d/j、bb_upper/middle/lower。"""
    ti = TechnicalIndicators(df)
    out: Dict[str, List[Optional[float]]] = {}
    for period in params.sma_periods:
        if period <= len(df):
            out[f"sma_{period}"] = nan_to_none(ti.sma(period))
    dif, dea, hist = ti.macd(params.macd_fast, params.macd_slow, params.macd_signal)
    out["macd_dif"], out["macd_dea"], out["macd_hist"] = nan_to_none(dif), nan_to_none(dea), nan_to_none(hist)
    out["rsi"] = nan_to_none(ti.rsi(params.rsi_period))
    k, d, j = ti.kdj(params.kdj_k, params.kdj_d, params.kdj_j)
    out["kdj_k"], out["kdj_d"], out["kdj_j"] = nan_to_none(k), nan_to_none(d), nan_to_none(j)
    upper, middle, lower = ti.bollinger_bands(params.bb_period, params.bb_std)
    out["bb_upper"], out["bb_middle"], out["bb_lower"] = nan_to_none(upper), nan_to_none(middle), nan_to_none(lower)
    return out


def compute_patterns(df: pd.DataFrame) -> Dict[str, List[int]]:
    return {name: _true_times(series) for name, series in CandlestickPatterns(df).get_all_patterns().items()}


def compute_signals(df: pd.DataFrame, config: SignalConfig) -> Tuple[List[int], List[int]]:
    detector = SignalDetector(df)
    return _true_times(detector.get_custom_entry_signals(config)), _true_times(detector.get_custom_exit_signals(config))


def compute_effectiveness(df: pd.DataFrame) -> Dict[str, EffectivenessStat]:
    raw = BacktestEngine(df).analyze_signal_effectiveness()
    return {name: EffectivenessStat(**stats) for name, stats in raw.items()}


def run_analysis(req: AnalysisRequest) -> AnalysisResponse:
    d = req.data
    df = fetch_klines(d.symbol, d.interval, d.start.isoformat(), d.end.isoformat())
    entry, exit_ = compute_signals(df, req.signals.to_config())
    return AnalysisResponse(
        indicators=compute_indicators(df, req.indicators),
        patterns=compute_patterns(df),
        entry_signals=entry,
        exit_signals=exit_,
        effectiveness=compute_effectiveness(df),
    )
