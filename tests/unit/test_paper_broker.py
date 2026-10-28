from decimal import Decimal

from conftest import _append, make_mark_price

from ai_trader.execution.paper import PaperBroker
from ai_trader.models import (
    Fill,
    OrderRequest,
    OrderResult,
    OrderStatus,
    OrderType,
    PositionSide,
    Side,
)


async def test_market_fill_with_slippage_and_fee(bus, state, exchange_info):
    state.update_mark(make_mark_price(mark=Decimal("80000"))); fills = []; bus.subscribe(Fill, lambda e: _append(fills, e))  # noqa: FURB157
    pb = PaperBroker(state, bus, exchange_info, slippage_bps=2); await bus.start(); await pb.start()
    res = await pb.submit(OrderRequest(symbol="BTCUSDT", side=Side.BUY, type=OrderType.MARKET, quantity=Decimal("0.002"), client_order_id="ait-1"))
    assert res.status == OrderStatus.FILLED and res.avg_price == Decimal("80016.00")
    await bus.drain(); assert fills[0].commission == Decimal("0.002") * Decimal("80016.00") * Decimal("0.0004")
    pos = await pb.positions(); assert pos["BTCUSDT"].side == PositionSide.LONG and pos["BTCUSDT"].quantity == Decimal("0.002")


async def test_stop_market_close_position_triggers_on_mark(bus, state, exchange_info):
    state.update_mark(make_mark_price(mark=Decimal(80000)))
    fills: list[Fill] = []
    results: list[OrderResult] = []
    bus.subscribe(Fill, lambda e: _append(fills, e))
    bus.subscribe(OrderResult, lambda e: _append(results, e))
    pb = PaperBroker(state, bus, exchange_info, slippage_bps=2)
    await bus.start()
    await pb.start()
    entry = await pb.submit(
        OrderRequest(
            symbol="BTCUSDT", side=Side.BUY, type=OrderType.MARKET,
            quantity=Decimal("0.002"), client_order_id="ait-entry",
        )
    )
    assert entry.avg_price == Decimal("80016.00")
    sl = await pb.submit(
        OrderRequest(
            symbol="BTCUSDT", side=Side.SELL, type=OrderType.STOP_MARKET,
            stop_price=Decimal("79000.0"), close_position=True, client_order_id="ait-sl",
        )
    )
    assert sl.status == OrderStatus.NEW
    assert await pb.open_order_symbols() == {"BTCUSDT"}

    bus.publish(make_mark_price(mark=Decimal(79500)))
    await bus.drain()
    pos = await pb.positions()
    assert pos["BTCUSDT"].quantity == Decimal("0.002")
    assert len(fills) == 1

    bus.publish(make_mark_price(mark=Decimal(78990)))
    await bus.drain()
    assert await pb.positions() == {}
    assert len(fills) == 2
    assert fills[-1].client_order_id == "ait-sl" and fills[-1].side == Side.SELL
    assert fills[-1].qty == Decimal("0.002")
    assert fills[-1].realized_pnl < 0
    assert [r.client_order_id for r in results] == ["ait-sl"]
    assert results[0].status == OrderStatus.FILLED
    assert await pb.open_order_symbols() == set()
    acc = await pb.account()
    expected_fees = fills[0].commission + fills[1].commission
    assert acc.total_wallet_balance == Decimal(10000) + fills[1].realized_pnl - expected_fees


async def test_take_profit_buy_triggers_below_stop_for_short(bus, state, exchange_info):
    state.update_mark(make_mark_price(mark=Decimal(80000)))
    fills: list[Fill] = []
    bus.subscribe(Fill, lambda e: _append(fills, e))
    pb = PaperBroker(state, bus, exchange_info, slippage_bps=0)
    await pb.start()
    await pb.submit(
        OrderRequest(
            symbol="BTCUSDT", side=Side.SELL, type=OrderType.MARKET,
            quantity=Decimal("0.002"), client_order_id="ait-short",
        )
    )
    assert (await pb.positions())["BTCUSDT"].side == PositionSide.SHORT
    await pb.submit(
        OrderRequest(
            symbol="BTCUSDT", side=Side.BUY, type=OrderType.TAKE_PROFIT_MARKET,
            stop_price=Decimal("78400.0"), close_position=True, client_order_id="ait-tp",
        )
    )
    bus.publish(make_mark_price(mark=Decimal(78500)))
    await bus.drain()
    assert "BTCUSDT" in await pb.positions()
    bus.publish(make_mark_price(mark=Decimal(78300)))
    await bus.drain()
    assert await pb.positions() == {}
    assert fills[-1].client_order_id == "ait-tp"
    assert fills[-1].realized_pnl == (Decimal(80000) - Decimal(78300)) * Decimal("0.002")


async def test_cancel_and_cancel_all_remove_pending_and_are_recorded(bus, state, exchange_info):
    state.update_mark(make_mark_price(mark=Decimal(80000)))
    pb = PaperBroker(state, bus, exchange_info)
    await pb.start()
    for cid, typ, stop in (("ait-a", OrderType.STOP_MARKET, "79000.0"), ("ait-b", OrderType.TAKE_PROFIT_MARKET, "81000.0")):
        await pb.submit(
            OrderRequest(
                symbol="BTCUSDT", side=Side.SELL, type=typ, stop_price=Decimal(stop),
                close_position=True, client_order_id=cid,
            )
        )
    canceled = await pb.cancel("BTCUSDT", "ait-a")
    assert canceled.status == OrderStatus.CANCELED and pb.cancel_calls == ["ait-a"]
    assert await pb.open_order_symbols() == {"BTCUSDT"}
    await pb.cancel_all("BTCUSDT")
    assert pb.cancel_all_calls == ["BTCUSDT"]
    assert await pb.open_order_symbols() == set()
    assert len(pb.submitted) == 2


async def test_close_position_submits_reduce_only_market(bus, state, exchange_info):
    state.update_mark(make_mark_price(mark=Decimal(80000)))
    pb = PaperBroker(state, bus, exchange_info)
    await pb.start()
    await pb.submit(
        OrderRequest(
            symbol="BTCUSDT", side=Side.BUY, type=OrderType.MARKET,
            quantity=Decimal("0.003"), client_order_id="ait-l",
        )
    )
    res = await pb.close_position("BTCUSDT")
    assert res is not None and res.status == OrderStatus.FILLED
    last = pb.submitted[-1]
    assert last.reduce_only and last.side == Side.SELL and last.type == OrderType.MARKET
    assert last.quantity == Decimal("0.003")
    assert await pb.positions() == {}


async def test_close_position_flat_returns_none(bus, state, exchange_info):
    pb = PaperBroker(state, bus, exchange_info); assert await pb.close_position("ETHUSDT") is None


async def test_positions_snapshot_matches_positions(bus, state, exchange_info):
    state.update_mark(make_mark_price(mark=Decimal(80000)))
    pb = PaperBroker(state, bus, exchange_info, slippage_bps=0)
    await pb.start()
    assert pb.positions_snapshot() == {}
    await pb.submit(OrderRequest(symbol="BTCUSDT", side=Side.SELL, type=OrderType.MARKET,
                                 quantity=Decimal("0.002"), client_order_id="ait-s"))
    snap = pb.positions_snapshot()
    assert snap == await pb.positions() and snap["BTCUSDT"].side == PositionSide.SHORT
