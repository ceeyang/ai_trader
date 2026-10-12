def test_fetch_klines_is_cached(fake_data_source, monkeypatch):
    from ai_trader.web.services import market_data as m

    m.reset_data_source()
    m.fetch_klines.cache_clear()
    calls = []
    ds = m.get_data_source()
    orig = ds.get_historical_data

    def counting(*a, **k):
        calls.append(1)
        return orig(*a, **k)

    monkeypatch.setattr(ds, "get_historical_data", counting)
    m.fetch_klines("BTCUSDT", "1d", "2024-02-01", "2024-02-29")
    m.fetch_klines("BTCUSDT", "1d", "2024-02-01", "2024-02-29")
    assert len(calls) == 1


def test_df_to_bars_time_is_unix_seconds(sample_ohlcv):
    from ai_trader.web.services.market_data import df_to_bars

    bars = df_to_bars(sample_ohlcv.head(1))
    assert bars[0].time == int(sample_ohlcv.index[0].timestamp())
    assert bars[0].close == float(sample_ohlcv["close"].iloc[0])


def test_nan_to_none(sample_ohlcv):
    import numpy as np
    import pandas as pd
    from ai_trader.web.services.market_data import nan_to_none

    assert nan_to_none(pd.Series([1.0, np.nan, 2.5])) == [1.0, None, 2.5]
