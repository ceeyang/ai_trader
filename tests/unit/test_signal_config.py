import pandas as pd

from ai_trader.core.analysis.patterns import CandlestickPatterns
from ai_trader.core.analysis.signals import SignalConfig, SignalDetector

ALL_FLAGS = [
    "trend_required", "macd_required", "rsi_required", "kdj_required",
    "bb_required", "pattern_required", "volume_required",
]


def test_entry_all_mode_equals_and_of_components(sample_ohlcv):
    d = SignalDetector(sample_ohlcv)
    cfg = SignalConfig()
    trend = d.get_trend_direction()
    macd, _ = d.get_macd_signals()
    rsi, _ = d.get_rsi_signals(30, 70)
    kdj, _ = d.get_kdj_signals()
    bb, _ = d.get_bollinger_signals()
    vol = d.get_volume_confirmation()
    pat = CandlestickPatterns(sample_ohlcv).get_bullish_patterns()
    expected = (trend == 1) & macd & rsi & kdj & bb & pat & vol
    pd.testing.assert_series_equal(d.get_custom_entry_signals(cfg), expected, check_names=False)


def test_entry_min_mode_counts_conditions(sample_ohlcv):
    d = SignalDetector(sample_ohlcv)
    cfg = SignalConfig(combination="min", min_conditions=2, pattern_required=False, volume_required=False)
    trend = d.get_trend_direction()
    macd, _ = d.get_macd_signals()
    rsi, _ = d.get_rsi_signals(30, 70)
    kdj, _ = d.get_kdj_signals()
    bb, _ = d.get_bollinger_signals()
    count = (trend == 1).astype(int) + macd.astype(int) + rsi.astype(int) + kdj.astype(int) + bb.astype(int)
    pd.testing.assert_series_equal(d.get_custom_entry_signals(cfg), count >= 2, check_names=False)


def test_min_conditions_above_enabled_returns_all_false(sample_ohlcv):
    d = SignalDetector(sample_ohlcv)
    cfg = SignalConfig(
        combination="min", min_conditions=3, trend_required=True,
        macd_required=False, rsi_required=False, kdj_required=False,
        bb_required=False, pattern_required=False, volume_required=False,
    )
    assert not d.get_custom_entry_signals(cfg).any()


def test_exit_is_or_of_enabled(sample_ohlcv):
    d = SignalDetector(sample_ohlcv)
    cfg = SignalConfig(trend_required=False, kdj_required=False, bb_required=False, pattern_required=False)
    _, macd = d.get_macd_signals()
    _, rsi = d.get_rsi_signals(30, 70)
    pd.testing.assert_series_equal(d.get_custom_exit_signals(cfg), macd | rsi, check_names=False)


def test_no_conditions_returns_all_false(sample_ohlcv):
    d = SignalDetector(sample_ohlcv)
    cfg = SignalConfig(**{k: False for k in ALL_FLAGS})
    assert not d.get_custom_entry_signals(cfg).any()
    assert not d.get_custom_exit_signals(cfg).any()
