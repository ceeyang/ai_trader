import logging
from decimal import Decimal

from conftest import T0, _append, make_decision, make_fill, make_mark_price

from ai_trader.execution.paper import PaperBroker
from ai_trader.execution.service import ExecutionService
from ai_trader.models import (
    Decision,
    Intent,
    OrderResult,
    OrderRole,
    OrderStatus,
    OrderType,
    RiskVerdict,
    Side,
)
from ai_trader.settings import Settings


class AlwaysApprove:
    def __init__(self, adjusted=None): self.adjusted = adjusted  # noqa: E704
    async def evaluate(self, d, acc): return RiskVerdict(approved=True, adjusted_notional=self.adjusted)
class AlwaysReject:
    async def evaluate(self, d, acc): return RiskVerdict(approved=False, reason="test")  # noqa: E704


class Clock:
    def __init__(self, t: float) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


async def _setup(bus, st, state, exchange_info, risk=None, clock=None):
    state.update_mark(make_mark_price(mark=Decimal(80000)))
    paper = PaperBroker(state, bus, exchange_info)
    await bus.start()
    await paper.start()
    svc = ExecutionService(
        bus, paper, risk or AlwaysApprove(), st, Settings(_env_file=None),
        state=state, clock=clock or (lambda: T0.timestamp()),
    )
    await svc.start()
    return paper, svc


async def test_approved_open_places_entry_then_sl_tp(bus, st, state, exchange_info):
    state.update_mark(make_mark_price(mark=Decimal("80000"))); paper = PaperBroker(state, bus, exchange_info); await bus.start(); await paper.start()  # noqa: FURB157
    svc = ExecutionService(bus, paper, AlwaysApprove(), st, Settings(_env_file=None), state=state, clock=lambda: T0.timestamp())
    await svc.handle_decision(make_decision(side=Side.BUY, notional=Decimal(160)))
    o = paper.submitted
    assert [x.type for x in o] == [OrderType.MARKET, OrderType.STOP_MARKET, OrderType.TAKE_PROFIT_MARKET]
    assert o[0].quantity == Decimal("0.002")
    assert o[1].close_position and o[1].side == Side.SELL and o[1].stop_price == Decimal("79215.80")   # 80016 × 0.99 向下取 tick
    assert o[2].stop_price == Decimal("81616.30")                                                      # 80016 × 1.02
    assert [(await st.get_order(x.client_order_id)).role for x in o] == [OrderRole.ENTRY, OrderRole.STOP_LOSS, OrderRole.TAKE_PROFIT]
    assert o[2].close_position and o[2].side == Side.SELL
    entry = await st.get_order(o[0].client_order_id)
    assert entry.status == OrderStatus.FILLED and entry.avg_price == Decimal("80016.00")


async def test_sell_entry_places_sl_above_and_tp_below(bus, st, state, exchange_info):
    paper, svc = await _setup(bus, st, state, exchange_info)
    await svc.handle_decision(make_decision(side=Side.SELL, notional=Decimal(160)))
    o = paper.submitted
    # SELL fills at 80000 × (1 − 0.0002) = 79984.00
    assert o[0].side == Side.SELL and o[1].side == Side.BUY and o[2].side == Side.BUY
    assert o[1].stop_price == Decimal("80783.80")  # 79984 × 1.01 = 80783.84 → tick
    assert o[2].stop_price == Decimal("78384.30")  # 79984 × 0.98 = 78384.32 → tick
    await svc.stop()


async def test_rejected_decision_places_nothing(bus, st, state, exchange_info):
    paper, svc = await _setup(bus, st, state, exchange_info, risk=AlwaysReject())
    await svc.handle_decision(make_decision(side=Side.BUY, notional=Decimal(160)))
    assert paper.submitted == []
    assert await st.count("orders") == 0
    await svc.stop()


async def test_adjusted_notional_used(bus, st, state, exchange_info):
    paper, svc = await _setup(bus, st, state, exchange_info, risk=AlwaysApprove(Decimal(200)))
    await svc.handle_decision(make_decision(side=Side.BUY, notional=Decimal(900)))
    assert paper.submitted[0].quantity == Decimal("0.002")
    await svc.stop()


async def test_open_skipped_when_filter_violation(bus, st, state, exchange_info, caplog):
    paper, svc = await _setup(bus, st, state, exchange_info)
    with caplog.at_level(logging.WARNING):
        await svc.handle_decision(make_decision(side=Side.BUY, notional=Decimal(50)))
    assert paper.submitted == []
    assert "FilterViolation" in caplog.text
    await svc.stop()


async def test_close_decision_cancels_protective_and_closes(bus, st, state, exchange_info):
    paper, svc = await _setup(bus, st, state, exchange_info)
    await svc.handle_decision(make_decision(side=Side.BUY, notional=Decimal(160)))
    sl_id, tp_id = paper.submitted[1].client_order_id, paper.submitted[2].client_order_id
    await svc.handle_decision(
        make_decision(side=Side.SELL, intent=Intent.CLOSE, notional=Decimal(160))
    )
    assert paper.cancel_all_calls == ["BTCUSDT"]
    assert paper.close_position_calls == ["BTCUSDT"]
    close_req = paper.submitted[-1]
    assert close_req.reduce_only and close_req.side == Side.SELL
    rec = await st.get_order(close_req.client_order_id)
    assert rec.role == OrderRole.CLOSE and rec.status == OrderStatus.FILLED
    assert (await st.get_order(sl_id)).status == OrderStatus.CANCELED
    assert (await st.get_order(tp_id)).status == OrderStatus.CANCELED
    assert await paper.positions() == {}
    await svc.stop()


async def test_protective_fill_cancels_sibling(bus, st, state, exchange_info):
    paper, svc = await _setup(bus, st, state, exchange_info)
    await svc.handle_decision(make_decision(side=Side.BUY, notional=Decimal(160)))
    sl_id, tp_id = paper.submitted[1].client_order_id, paper.submitted[2].client_order_id
    bus.publish(make_fill(sl_id))
    await bus.drain()
    assert paper.cancel_calls == [tp_id]
    assert (await st.get_order(tp_id)).status == OrderStatus.CANCELED
    assert await st.count("fills") >= 2  # entry fill + the published SL fill
    await svc.stop()


async def test_protective_trigger_via_mark_cancels_sibling_once(bus, st, state, exchange_info):
    paper, svc = await _setup(bus, st, state, exchange_info)
    await svc.handle_decision(make_decision(side=Side.BUY, notional=Decimal(160)))
    sl_id, tp_id = paper.submitted[1].client_order_id, paper.submitted[2].client_order_id
    bus.publish(make_mark_price(mark=Decimal(79000)))  # below SL 79215.80
    await bus.drain()
    assert paper.cancel_calls == [tp_id]  # Fill and OrderResult both arrive; only one cancel
    assert (await st.get_order(sl_id)).status == OrderStatus.FILLED
    assert (await st.get_order(tp_id)).status == OrderStatus.CANCELED
    assert await paper.positions() == {}
    await svc.stop()


async def test_max_hold_emits_close(bus, st, state, exchange_info):
    clock = Clock(T0.timestamp())
    paper, svc = await _setup(bus, st, state, exchange_info, clock=clock)
    decisions: list[Decision] = []
    bus.subscribe(Decision, lambda e: _append(decisions, e))
    await svc.handle_decision(make_decision(side=Side.BUY, notional=Decimal(160)))
    await svc.enforce_max_hold()
    await bus.drain()
    assert decisions == []  # not yet past max_hold_s
    clock.t = T0.timestamp() + 14401
    await svc.enforce_max_hold()
    await bus.drain()
    assert [d.intent for d in decisions] == [Intent.CLOSE]
    d = decisions[0]
    assert d.symbol == "BTCUSDT" and d.side == Side.SELL
    assert d.notional_usdt == Decimal("0.002") * Decimal(80000)
    assert await st.count("decisions") == 1
    # the service consumes its own CLOSE decision and flattens the position
    assert paper.close_position_calls == ["BTCUSDT"]
    assert await paper.positions() == {}
    await svc.enforce_max_hold()
    await bus.drain()
    assert len(decisions) == 1  # nothing left to time out
    await svc.stop()


async def test_order_result_updates_status(bus, st, state, exchange_info):
    paper, svc = await _setup(bus, st, state, exchange_info)
    await svc.handle_decision(make_decision(side=Side.BUY, notional=Decimal(160)))
    tp = paper.submitted[2]
    bus.publish(
        OrderResult(
            order_id=99, client_order_id=tp.client_order_id, symbol="BTCUSDT", side=Side.SELL,
            type=OrderType.TAKE_PROFIT_MARKET, status=OrderStatus.EXPIRED, orig_qty=Decimal(0),
            executed_qty=Decimal(0), avg_price=Decimal(0), stop_price=tp.stop_price,
            reduce_only=False, close_position=True, update_time=T0,
        )
    )
    await bus.drain()
    rec = await st.get_order(tp.client_order_id)
    assert rec.status == OrderStatus.EXPIRED and rec.order_id == 99
    assert paper.cancel_calls == []
    await svc.stop()
