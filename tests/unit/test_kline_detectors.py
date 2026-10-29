from datetime import timedelta
from decimal import Decimal

from conftest import T0, make_mark_price

from ai_trader.analysis.detectors.breakout import BreakoutDetector
from ai_trader.analysis.detectors.mean_reversion import MeanReversionDetector
from ai_trader.data.market_state import MarketState
from ai_trader.models import Direction, Kline
from ai_trader.settings import DetectorConfig


def make_kline(
    i: int,
    close: float,
    *,
    high: float | None = None,
    low: float | None = None,
    volume: float = 10,
    symbol: str = "BTCUSDT",
    is_closed: bool = True,
) -> Kline:
    c = Decimal(str(close))
    return Kline(
        symbol=symbol,
        interval="1m",
        open_time=T0 + timedelta(minutes=i),
        close_time=T0 + timedelta(minutes=i + 1) - timedelta(milliseconds=1),
        open=c,
        high=Decimal(str(high if high is not None else close)),
        low=Decimal(str(low if low is not None else close)),
        close=c,
        volume=Decimal(str(volume)),
        is_closed=is_closed,
    )


async def _feed_range(det, n: int, *, symbol: str = "BTCUSDT") -> None:
    """n flat candles: high 101, low 99, close 100, volume 10."""
    for i in range(n):
        assert await det.on_event(make_kline(i, 100, high=101, low=99, symbol=symbol)) == []


# ---- breakout ---------------------------------------------------------------


async def test_breakout_bullish_on_volume_confirmed_upside_break():
    det = BreakoutDetector(DetectorConfig(), MarketState(), clock=lambda: 0.0)
    await _feed_range(det, 60)
    sigs = await det.on_event(make_kline(60, 101.5, high=101.6, low=100, volume=20))
    assert len(sigs) == 1
    s = sigs[0]
    assert s.direction == Direction.BULLISH and s.detector == "breakout"
    assert abs(s.strength - 0.75) < 1e-9  # ratio 2.0 → 0.5 + 0.5 × 1 / 2
    assert s.ref_price == Decimal("101.5")
    assert (s.expires_at - s.created_at).total_seconds() == 1800
    assert "101" in s.rationale and "2.00x" in s.rationale


async def test_breakout_ignores_low_volume_break_and_small_move():
    det = BreakoutDetector(DetectorConfig(), MarketState(), clock=lambda: 0.0)
    await _feed_range(det, 60)
    assert await det.on_event(make_kline(60, 101.5, high=101.6, volume=12)) == []  # 1.2x < 1.5x
    det2 = BreakoutDetector(DetectorConfig(), MarketState(), clock=lambda: 0.0)
    await _feed_range(det2, 60)
    assert await det2.on_event(make_kline(60, 101.1, high=101.1, volume=30)) == []  # +0.099 % < 0.15 %


async def test_breakout_bearish_on_downside_break_uses_mark_price():
    state = MarketState()
    state.update_mark(make_mark_price(mark=Decimal("98.4")))
    det = BreakoutDetector(DetectorConfig(), state, clock=lambda: 0.0)
    await _feed_range(det, 60)
    sigs = await det.on_event(make_kline(60, 98.5, high=99, low=98.4, volume=50))
    assert sigs[0].direction == Direction.BEARISH and sigs[0].strength == 1.0
    assert sigs[0].ref_price == Decimal("98.4")


async def test_breakout_needs_full_history_and_ignores_open_candles():
    det = BreakoutDetector(DetectorConfig(), MarketState(), clock=lambda: 0.0)
    await _feed_range(det, 59)
    assert await det.on_event(make_kline(59, 105, high=105, volume=50, is_closed=False)) == []
    # 59 candles of history only → still no signal on the 60th
    assert await det.on_event(make_kline(59, 105, high=105, volume=50)) == []


async def test_breakout_respects_cooldown_per_symbol():
    t = [0.0]
    det = BreakoutDetector(DetectorConfig(breakout_lookback=5), MarketState(), clock=lambda: t[0])
    await _feed_range(det, 5)
    assert len(await det.on_event(make_kline(5, 102, high=102, volume=30))) == 1
    assert await det.on_event(make_kline(6, 104, high=104, volume=60)) == []  # cooling down
    t[0] = 901
    assert len(await det.on_event(make_kline(7, 106, high=106, volume=60))) == 1


async def test_breakout_reads_cfg_at_call_time():
    cfg = DetectorConfig()
    det = BreakoutDetector(cfg, MarketState(), clock=lambda: 0.0)
    await _feed_range(det, 60)
    cfg.breakout_volume_mult = 3.0
    assert await det.on_event(make_kline(60, 101.5, high=101.6, volume=20)) == []  # 2x < 3x now
    cfg.breakout_volume_mult = 1.5
    assert len(await det.on_event(make_kline(61, 101.8, high=101.9, volume=20))) == 1


# ---- mean reversion ---------------------------------------------------------


async def _feed_closes(det, n: int) -> None:
    """n closes alternating 100 / 101."""
    for i in range(n):
        assert await det.on_event(make_kline(i, 100 + (i % 2))) == []


async def test_mean_reversion_bearish_on_high_z_and_bullish_on_low_z():
    t = [0.0]
    det = MeanReversionDetector(DetectorConfig(), MarketState(), clock=lambda: t[0])
    await _feed_closes(det, 29)
    sigs = await det.on_event(make_kline(29, 105))
    assert len(sigs) == 1 and sigs[0].direction == Direction.BEARISH and sigs[0].detector == "mean_reversion"
    assert 0.5 <= sigs[0].strength <= 1.0
    assert (sigs[0].expires_at - sigs[0].created_at).total_seconds() == 1200
    assert "z=" in sigs[0].rationale and "mean" in sigs[0].rationale and "stdev" in sigs[0].rationale

    det2 = MeanReversionDetector(DetectorConfig(), MarketState(), clock=lambda: 0.0)
    await _feed_closes(det2, 29)
    assert (await det2.on_event(make_kline(29, 96)))[0].direction == Direction.BULLISH


async def test_mean_reversion_silent_inside_band_and_on_flat_or_short_history():
    det = MeanReversionDetector(DetectorConfig(), MarketState(), clock=lambda: 0.0)
    await _feed_closes(det, 29)
    assert await det.on_event(make_kline(29, 101)) == []  # |z| ≈ 1

    flat = MeanReversionDetector(DetectorConfig(), MarketState(), clock=lambda: 0.0)
    for i in range(30):
        assert await flat.on_event(make_kline(i, 100)) == []  # stdev 0

    short = MeanReversionDetector(DetectorConfig(), MarketState(), clock=lambda: 0.0)
    await _feed_closes(short, 10)
    assert await short.on_event(make_kline(10, 120)) == []  # < 30 candles
    assert await short.on_event(make_kline(11, 120, is_closed=False)) == []


async def test_mean_reversion_cooldown_and_cfg_read_at_call_time():
    cfg = DetectorConfig()
    t = [0.0]
    det = MeanReversionDetector(cfg, MarketState(), clock=lambda: t[0])
    await _feed_closes(det, 29)
    cfg.mr_z_entry = 10.0
    assert await det.on_event(make_kline(29, 105)) == []  # z ≈ 4.6 < 10
    cfg.mr_z_entry = 2.5
    assert len(await det.on_event(make_kline(30, 110))) == 1
    assert await det.on_event(make_kline(31, 120)) == []  # cooling down
    t[0] = 901
    assert len(await det.on_event(make_kline(32, 130))) == 1
