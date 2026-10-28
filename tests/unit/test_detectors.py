from datetime import timedelta
from decimal import Decimal

from conftest import T0, _append, make_liq, make_mark_price, make_signal

from ai_trader.analysis.detectors.base import DetectorRunner
from ai_trader.analysis.detectors.funding_extreme import FundingExtremeDetector
from ai_trader.analysis.detectors.liquidation_burst import LiquidationBurstDetector
from ai_trader.bus import EventBus
from ai_trader.data.market_state import MarketState
from ai_trader.models import Direction, MarkPrice, Side, Signal
from ai_trader.settings import DetectorConfig
from ai_trader.storage.db import Store


async def test_funding_extreme_bearish_once_per_period():
    det = FundingExtremeDetector(DetectorConfig(), MarketState(), clock=lambda: 0.0)
    mp = make_mark_price(funding_rate=Decimal("0.0005"))  # 年化 0.5475 ≥ 0.30 → BEARISH, strength = 0.5475/0.6
    sigs = await det.on_event(mp)
    assert len(sigs) == 1 and sigs[0].direction == Direction.BEARISH and abs(sigs[0].strength - 0.9125) < 1e-3
    assert sigs[0].expires_at == mp.next_funding_time and sigs[0].detector == "funding_extreme"
    assert await det.on_event(mp) == []


async def test_funding_negative_is_bullish_and_below_threshold_silent():
    det = FundingExtremeDetector(DetectorConfig(), MarketState(), clock=lambda: 0.0)
    assert (await det.on_event(make_mark_price(funding_rate=Decimal("-0.0004"))))[0].direction == Direction.BULLISH
    assert await det.on_event(make_mark_price(funding_rate=Decimal("0.0001"), next_funding_time=T0 + timedelta(hours=16))) == []


async def test_liquidation_burst_bullish_on_long_liquidations_with_cooldown():
    t = [0.0]
    det = LiquidationBurstDetector(DetectorConfig(liquidation_notional_threshold_usdt=Decimal("1000")), MarketState(), clock=lambda: t[0])  # noqa: FURB157
    assert await det.on_event(make_liq(Side.SELL, price=Decimal("100"), qty=Decimal("6"))) == []  # 600 < 1000  # noqa: FURB157
    sigs = await det.on_event(make_liq(Side.SELL, price=Decimal("100"), qty=Decimal("6")))  # 1200 ≥ 1000  # noqa: FURB157
    assert sigs[0].direction == Direction.BULLISH and abs(sigs[0].strength - 0.6) < 1e-9
    assert await det.on_event(make_liq(Side.SELL, price=Decimal("100"), qty=Decimal("50"))) == []  # 冷却中  # noqa: FURB157
    t[0] = 1000
    assert (await det.on_event(make_liq(Side.BUY, price=Decimal("100"), qty=Decimal("20"))))[0].direction == Direction.BEARISH  # noqa: FURB157


async def test_runner_persists_then_publishes(tmp_path):
    class Fake:
        name = "fake"
        subscribes_to = (MarkPrice,)

        async def on_event(self, e):
            return [make_signal("z", detector="fake")]

    st = Store(tmp_path / "t.db")
    await st.open()
    bus = EventBus()
    got = []
    bus.subscribe(Signal, lambda e: _append(got, e))
    DetectorRunner(bus, st, [Fake()])
    await bus.start()
    bus.publish(make_mark_price())
    await bus.drain()
    await bus.stop()
    assert len(got) == 1 and (await st.recent_signals(5))[0].id == "z"
    await st.close()


async def test_funding_detector_rereads_cfg_at_call_time():
    """The AutoTuner (a later task) mutates `DetectorConfig` in place at runtime, so the
    detector must read `cfg.funding_annualized_threshold` on each call rather than
    copying it at construction."""
    cfg = DetectorConfig()
    det = FundingExtremeDetector(cfg, MarketState(), clock=lambda: 0.0)
    mp = make_mark_price(funding_rate=Decimal("0.0001"))  # annualized 0.1095 < default 0.30 threshold
    assert await det.on_event(mp) == []
    cfg.funding_annualized_threshold = Decimal("0.05")
    sigs = await det.on_event(mp)
    assert sigs and sigs[0].direction == Direction.BEARISH


async def test_liquidation_detector_rereads_cfg_at_call_time():
    """Same live-mutation requirement as above, for the liquidation detector's
    threshold."""
    cfg = DetectorConfig(liquidation_notional_threshold_usdt=Decimal("1000"))  # noqa: FURB157
    det = LiquidationBurstDetector(cfg, MarketState(), clock=lambda: 0.0)
    liq = make_liq(Side.SELL, price=Decimal("100"), qty=Decimal("6"))  # notional 600 < 1000  # noqa: FURB157
    assert await det.on_event(liq) == []
    cfg.liquidation_notional_threshold_usdt = Decimal("100")  # noqa: FURB157
    sigs = await det.on_event(liq)  # cumulative 1200 >= new threshold 100
    assert sigs and sigs[0].direction == Direction.BULLISH
