from datetime import datetime


def test_sample_ohlcv_shape(sample_ohlcv):
    assert len(sample_ohlcv) == 400
    assert list(sample_ohlcv.columns) == ["open", "high", "low", "close", "volume"]
    assert (sample_ohlcv["high"] >= sample_ohlcv[["open", "close"]].max(axis=1)).all()
    assert (sample_ohlcv["low"] <= sample_ohlcv[["open", "close"]].min(axis=1)).all()


def test_sample_is_deterministic():
    from tests.conftest import make_sample_ohlcv

    assert make_sample_ohlcv().equals(make_sample_ohlcv())


def test_fake_data_source_slices(fake_data_source):
    from ai_trader.core.data.providers.binance import BinanceDataSource

    ds = BinanceDataSource()
    ds.connect()
    df = ds.get_historical_data("BTCUSDT", "1d", datetime(2024, 3, 1), datetime(2024, 3, 31))
    assert len(df) == 31
