import asyncio
from datetime import UTC, datetime
from decimal import Decimal

from conftest import _append, fx, make_mark_price

from ai_trader.bus import EventBus
from ai_trader.data import market_feed as market_feed_module
from ai_trader.data.market_feed import MarketFeed, MarkPriceSampler, StalenessWatchdog, build_stream_names
from ai_trader.data.market_state import MarketState
from ai_trader.exchange.binance.parsers import parse_mark_price
from ai_trader.models import DataFresh, DataStale, Liquidation, MarkPrice
from ai_trader.storage.db import Store


def test_build_stream_names():
    assert build_stream_names(["BTCUSDT"]) == ["btcusdt@markPrice@1s", "btcusdt@kline_1m", "btcusdt@forceOrder"]


async def test_feed_handle_publishes_typed_events_and_updates_state():
    bus = EventBus(); state = MarketState(); got = []
    bus.subscribe(MarkPrice, lambda e: _append(got, e)); bus.subscribe(Liquidation, lambda e: _append(got, e))
    feed = MarketFeed(bus, state, "wss://x", ["BTCUSDT"])
    await bus.start(); await feed.handle(fx("ws_mark_price.json")); await feed.handle(fx("ws_force_order.json"))
    await bus.drain(); await bus.stop()
    assert {type(e).__name__ for e in got} == {"MarkPrice", "Liquidation"}
    assert state.mark("BTCUSDT").mark_price == Decimal("80874.42344203")


async def test_watchdog_emits_stale_then_fresh():
    t = [0.0]; clock = lambda: t[0]
    bus = EventBus(); state = MarketState(clock=clock); events = []
    bus.subscribe(DataStale, lambda e: _append(events, e)); bus.subscribe(DataFresh, lambda e: _append(events, e))
    wd = StalenessWatchdog(bus, state, ["BTCUSDT"], max_age_s=10, check_interval_s=0.01, clock=clock)
    await bus.start(); task = asyncio.create_task(wd.run())
    state.update_mark(parse_mark_price(fx("ws_mark_price.json"))); t[0] = 5; await asyncio.sleep(0.05)
    assert wd.is_stale("BTCUSDT") is False
    t[0] = 20; await asyncio.sleep(0.05); await bus.drain()
    assert isinstance(events[-1], DataStale) and events[-1].age_s >= 10
    state.update_mark(parse_mark_price(fx("ws_mark_price.json"))); await asyncio.sleep(0.05); await bus.drain()
    assert isinstance(events[-1], DataFresh)
    await wd.stop(); await task; await bus.stop()


async def test_sampler_writes_at_most_once_per_interval(tmp_path):
    t = [0.0]; st = Store(tmp_path / "t.db"); await st.open(); bus = EventBus()
    MarkPriceSampler(bus, st, interval_s=10, clock=lambda: t[0]); await bus.start()
    for _ in range(3): bus.publish(make_mark_price())
    await bus.drain(); assert await st.count("mark_samples") == 1
    t[0] = 10; bus.publish(make_mark_price()); await bus.drain(); assert await st.count("mark_samples") == 2
    await bus.stop(); await st.close()


async def test_sampler_does_not_nudge_timestamps_across_symbols(tmp_path, monkeypatch):
    """Two different symbols sampled at the same tick must both be written as-is: the
    `mark_samples` primary key is `(symbol, ts)`, so distinct symbols sharing a `ts` never
    collide and the per-symbol nudge must not fire for either of them. A global (not
    per-symbol) nudge would have bumped the second symbol's timestamp by 1us here."""
    fixed = datetime(2026, 10, 29, 0, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(market_feed_module, "utc_now", lambda: fixed)
    st = Store(tmp_path / "t.db"); await st.open(); bus = EventBus()
    MarkPriceSampler(bus, st, interval_s=10, clock=lambda: 0.0); await bus.start()
    bus.publish(make_mark_price(symbol="BTCUSDT")); bus.publish(make_mark_price(symbol="ETHUSDT"))
    await bus.drain()
    assert await st.count("mark_samples") == 2
    assert await st.mark_at("BTCUSDT", fixed, tolerance_s=0) == Decimal(80000)
    assert await st.mark_at("ETHUSDT", fixed, tolerance_s=0) == Decimal(80000)
    await bus.stop(); await st.close()


async def test_watchdog_emits_stale_immediately_when_no_data():
    bus = EventBus(); state = MarketState(); events = []
    bus.subscribe(DataStale, lambda e: _append(events, e))
    wd = StalenessWatchdog(bus, state, ["BTCUSDT"], max_age_s=10, check_interval_s=0.01)
    await bus.start(); task = asyncio.create_task(wd.run())
    await asyncio.sleep(0.05); await bus.drain()
    assert wd.is_stale("BTCUSDT") is True
    assert isinstance(events[-1], DataStale) and events[-1].age_s == float("inf")
    await wd.stop(); await task; await bus.stop()
