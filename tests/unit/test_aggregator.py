# tests/unit/test_aggregator.py
from datetime import timedelta
from decimal import Decimal

from conftest import T0, _append, make_position, make_signal

from ai_trader.data.market_state import MarketState
from ai_trader.models import Decision, Direction, Intent, PositionSide, Side
from ai_trader.settings import StrategyConfig
from ai_trader.strategy.aggregator import SignalAggregator


def make_agg(bus, st, positions=None, clock=None, **cfg):
    return SignalAggregator(
        bus,
        st,
        MarketState(),
        StrategyConfig(**cfg),
        positions=lambda: positions or {},
        clock=clock or (lambda: T0.timestamp()),
    )


async def test_score_weights_and_decay(bus, st):
    agg = make_agg(bus, st, signal_half_life_s=1800, entry_threshold=9.0)
    await agg.on_signal(
        make_signal(
            "a", detector="news_sentiment", strength=0.5, created_at=T0, expires_at=T0 + timedelta(hours=4)
        )
    )
    assert abs(agg.score("BTCUSDT", now=T0.timestamp()) - 0.5) < 1e-9
    assert abs(agg.score("BTCUSDT", now=T0.timestamp() + 1800) - 0.25) < 1e-9
    await agg.on_signal(
        make_signal(
            "b", detector="funding_extreme", strength=1.0, created_at=T0, expires_at=T0 + timedelta(hours=4)
        )
    )
    assert abs(agg.score("BTCUSDT", now=T0.timestamp()) - 1.0) < 1e-9  # 0.5 + 1.0×0.5


async def test_expired_signals_ignored(bus, st):
    agg = make_agg(bus, st)
    await agg.on_signal(
        make_signal(
            "a",
            strength=1.0,
            created_at=T0 - timedelta(hours=2),
            expires_at=T0 - timedelta(hours=1),
        )
    )
    assert agg.score("BTCUSDT") == 0.0


async def test_open_decision_when_threshold_crossed_and_notional_scaled(bus, st):
    got = []
    bus.subscribe(Decision, lambda d: _append(got, d))
    await bus.start()
    agg = make_agg(bus, st)
    await agg.on_signal(
        make_signal(
            "a",
            detector="news_sentiment",
            direction=Direction.BEARISH,
            strength=0.7,
            created_at=T0,
            expires_at=T0 + timedelta(hours=4),
        )
    )
    await bus.drain()
    d = got[0]
    assert (
        d.intent == Intent.OPEN
        and d.side == Side.SELL
        and d.notional_usdt == Decimal("70")  # noqa: FURB157
        and d.signal_ids == ["a"]
        and d.stop_loss_pct == Decimal("0.01")
    )
    assert (await st.count("decisions")) == 1


async def test_cooldown_blocks_second_decision(bus, st):
    # detector="news_sentiment" (weight 1.0): strength 0.9 -> score 0.9 >= entry_threshold
    # 0.6. The brief's literal data used the default detector ("funding_extreme",
    # weight 0.5), whose weighted score (0.45) never crosses the default
    # entry_threshold (0.6) -- that combination can't demonstrate cooldown at all, so
    # the detector is pinned here to the one that makes the scenario reachable.
    t = [T0.timestamp()]
    agg = make_agg(bus, st, clock=lambda: t[0])
    assert (
        await agg.on_signal(
            make_signal("a", detector="news_sentiment", strength=0.9, created_at=T0, expires_at=T0 + timedelta(hours=4))
        )
        is not None
    )
    assert (
        await agg.on_signal(
            make_signal("b", detector="news_sentiment", strength=0.9, created_at=T0, expires_at=T0 + timedelta(hours=4))
        )
        is None
    )
    t[0] += 900
    assert (
        await agg.on_signal(
            make_signal("c", detector="news_sentiment", strength=0.9, created_at=T0, expires_at=T0 + timedelta(hours=4))
        )
        is not None
    )


async def test_close_decision_on_flip_with_open_position(bus, st):
    pos = {"BTCUSDT": make_position(PositionSide.LONG, Decimal("0.002"), Decimal("80000"))}  # noqa: FURB157
    agg = make_agg(bus, st, positions=pos)
    d = await agg.on_signal(
        make_signal(
            "b",
            detector="news_sentiment",
            direction=Direction.BEARISH,
            strength=0.5,
            created_at=T0,
            expires_at=T0 + timedelta(hours=1),
        )
    )
    assert d.intent == Intent.CLOSE and d.side == Side.SELL and d.notional_usdt == Decimal("160")  # noqa: FURB157


async def test_no_open_when_position_exists_same_direction(bus, st):
    pos = {"BTCUSDT": make_position(PositionSide.LONG, Decimal("0.002"), Decimal("80000"))}  # noqa: FURB157
    assert (
        await make_agg(bus, st, positions=pos).on_signal(
            make_signal("a", strength=0.9, created_at=T0, expires_at=T0 + timedelta(hours=1))
        )
        is None
    )


async def test_entry_threshold_read_at_call_time(bus, st):
    """cfg is mutable; a post-construction change must change the outcome (no caching)."""
    cfg = StrategyConfig(entry_threshold=0.95)
    agg = SignalAggregator(bus, st, MarketState(), cfg, positions=dict, clock=lambda: T0.timestamp())
    assert (
        await agg.on_signal(make_signal("a", strength=0.9, created_at=T0, expires_at=T0 + timedelta(hours=4)))
        is None
    )
    cfg.entry_threshold = 0.5
    d = await agg.on_signal(make_signal("b", strength=0.9, created_at=T0, expires_at=T0 + timedelta(hours=4)))
    assert d is not None and d.intent == Intent.OPEN


async def test_start_subscribes_and_backfills_last_decision_at(bus, st):
    await st.insert_decision(
        Decision(
            id="prev",
            symbol="BTCUSDT",
            side=Side.BUY,
            intent=Intent.OPEN,
            notional_usdt=Decimal("100"),  # noqa: FURB157
            score=0.9,
            signal_ids=[],
            created_at=T0,
            stop_loss_pct=Decimal("0.01"),
            take_profit_pct=Decimal("0.02"),
            max_hold_s=3600,
        )
    )
    got = []
    bus.subscribe(Decision, lambda d: _append(got, d))
    await bus.start()
    t = [T0.timestamp() + 100]  # within cooldown of the backfilled decision
    agg = make_agg(bus, st, clock=lambda: t[0])
    await agg.start()
    bus.publish(make_signal("x", strength=0.9, created_at=T0, expires_at=T0 + timedelta(hours=4)))
    await bus.drain()
    assert got == []  # still in cooldown, so start() must have backfilled _last_decision_at
