def test_sma_longer_than_data_is_skipped(sample_ohlcv):
    from ai_trader.web.schemas import IndicatorParams
    from ai_trader.web.services.analysis import compute_indicators

    out = compute_indicators(sample_ohlcv.head(100), IndicatorParams(sma_periods=[20, 200]))
    assert "sma_20" in out and "sma_200" not in out
    assert len(out["sma_20"]) == 100 and out["sma_20"][0] is None
    assert {"macd_dif", "macd_dea", "macd_hist", "rsi", "kdj_k", "kdj_d", "kdj_j", "bb_upper", "bb_middle", "bb_lower"} <= set(out)


def test_patterns_are_unix_seconds(sample_ohlcv):
    from ai_trader.web.services.analysis import compute_patterns

    out = compute_patterns(sample_ohlcv)
    assert "hammer" in out and all(isinstance(t, int) for t in out["hammer"])


def test_signal_params_to_config_roundtrip():
    from ai_trader.core.analysis.signals import SignalConfig
    from ai_trader.web.schemas import SignalParams

    assert SignalParams().to_config() == SignalConfig()
    assert SignalParams(combination="min", min_conditions=3).to_config().min_conditions == 3
