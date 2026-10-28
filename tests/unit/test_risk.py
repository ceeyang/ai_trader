from datetime import timedelta
from decimal import Decimal

from conftest import T0, _append, make_account, make_decision, make_fill, make_position

from ai_trader.bus import EventBus
from ai_trader.models import Decision, Intent, KillSwitchTriggered, PositionSide, RiskVerdict
from ai_trader.risk.engine import RiskEngine
from ai_trader.risk.kill_switch import KillSwitch
from ai_trader.settings import RiskLimits
from ai_trader.storage.db import Store

ACC = make_account(wallet=Decimal("10000"), positions=[])  # noqa: FURB157


def make_engine(st: Store, state, **limits) -> RiskEngine:
    return RiskEngine(
        RiskLimits(**limits), st, state, ["BTCUSDT", "ETHUSDT"], clock=lambda: T0.timestamp()
    )


async def evaluate(engine: RiskEngine, st: Store, d: Decision, acc=ACC) -> RiskVerdict:
    """The real pipeline (`SignalAggregator.on_signal`) always persists a `Decision`
    before publishing it, and `risk_verdicts.decision_id` references `decisions(id)`;
    insert it here too so `evaluate` sees the same precondition it would in production."""
    await st.insert_decision(d)
    return await engine.evaluate(d, acc)


async def test_approves_normal_open(st, state_fresh):
    v = await evaluate(make_engine(st, state_fresh), st, make_decision(notional=Decimal("100")))  # noqa: FURB157
    assert v.approved and v.reason is None and v.adjusted_notional is None


async def test_adjusts_notional_above_max(st, state_fresh):
    v = await evaluate(make_engine(st, state_fresh), st, make_decision(notional=Decimal("900")))  # noqa: FURB157
    assert v.approved and v.adjusted_notional == Decimal("200")  # noqa: FURB157


async def test_kill_switch_rejects_everything_including_close(st, state_fresh):
    await st.set_kv("kill_switch", "1")
    v = await evaluate(make_engine(st, state_fresh), st, make_decision(intent=Intent.CLOSE))
    assert v.reason == "kill_switch"


async def test_symbol_not_allowed(st, state_fresh):
    v = await evaluate(make_engine(st, state_fresh), st, make_decision(symbol="DOGEUSDT"))
    assert v.reason == "symbol_not_allowed"


async def test_stale_blocks_open_but_allows_close(st, state_stale):
    e = make_engine(st, state_stale)
    v_open = await evaluate(e, st, make_decision())
    assert v_open.reason == "data_stale"
    v_close = await evaluate(e, st, make_decision(intent=Intent.CLOSE))
    assert v_close.approved


async def test_total_exposure(st, state_fresh):
    acc = make_account(
        wallet=Decimal("10000"),  # noqa: FURB157
        positions=[make_position(PositionSide.LONG, Decimal("0.005"), Decimal("80000"))],  # noqa: FURB157
    )  # open notional 400
    v = await evaluate(
        make_engine(st, state_fresh),
        st,
        make_decision(notional=Decimal("150"), symbol="ETHUSDT"),  # noqa: FURB157
        acc,
    )
    assert v.reason == "max_total_exposure"


async def test_max_open_positions(st, state_fresh):
    acc = make_account(
        wallet=Decimal("10000"),  # noqa: FURB157
        positions=[
            make_position(PositionSide.LONG, Decimal("0.001"), Decimal("80000")),  # noqa: FURB157
            make_position(
                PositionSide.SHORT, Decimal("0.01"), Decimal("3000"), symbol="ETHUSDT"  # noqa: FURB157
            ),
        ],
    )
    e = make_engine(st, state_fresh, max_total_exposure_usdt=Decimal("5000"))  # noqa: FURB157
    v = await evaluate(e, st, make_decision(notional=Decimal("100")), acc)  # noqa: FURB157
    assert v.reason == "max_open_positions"


async def test_daily_loss_limit_and_reset_on_new_utc_day(st, state_fresh):
    # first evaluate of the day writes day_start_equity:2026-10-29 = 10000
    await evaluate(make_engine(st, state_fresh), st, make_decision())
    await st.insert_fill(
        make_fill("c1", realized_pnl=Decimal("-600"), event_time=T0 + timedelta(hours=1))  # noqa: FURB157
    )

    e2 = RiskEngine(
        RiskLimits(), st, state_fresh, ["BTCUSDT"], clock=lambda: (T0 + timedelta(hours=2)).timestamp()
    )
    v2 = await evaluate(e2, st, make_decision())
    assert v2.reason == "daily_loss_limit"

    e3 = RiskEngine(
        RiskLimits(),
        st,
        state_fresh,
        ["BTCUSDT"],
        clock=lambda: (T0 + timedelta(days=1, hours=1)).timestamp(),
    )
    v3 = await evaluate(e3, st, make_decision())
    assert v3.approved


async def test_consecutive_losses(st, state_fresh):
    for i in range(3):
        await st.insert_fill(
            make_fill(f"c{i}", realized_pnl=Decimal("-1"), event_time=T0 + timedelta(minutes=i))  # noqa: FURB157
        )
    v = await evaluate(make_engine(st, state_fresh), st, make_decision())
    assert v.reason == "consecutive_losses"


async def test_verdicts_persisted(st, state_fresh):
    await evaluate(make_engine(st, state_fresh), st, make_decision())
    assert await st.count("risk_verdicts") == 1


async def test_kill_switch_cancels_and_closes(st):
    class FakeBroker:
        def __init__(self):
            self.cancel_all_calls, self.close_calls = set(), []
            self.calls: list[tuple[str, str]] = []  # ordered log: (op, symbol)

        async def positions(self):
            return {"BTCUSDT": make_position(PositionSide.LONG, Decimal("0.002"), Decimal("80000"))}  # noqa: FURB157

        async def open_order_symbols(self):
            return {"ETHUSDT"}

        async def cancel_all(self, s):
            self.cancel_all_calls.add(s)
            self.calls.append(("cancel_all", s))

        async def close_position(self, s):
            self.close_calls.append(s)
            self.calls.append(("close_position", s))
            return None  # noqa: PLR1711, RET501

    broker = FakeBroker()
    bus = EventBus()
    events = []
    bus.subscribe(KillSwitchTriggered, lambda e: _append(events, e))
    ks = KillSwitch(st, broker, bus)
    await bus.start()
    await ks.trigger("test")
    await bus.drain()
    await bus.stop()

    assert await ks.is_active()
    assert broker.cancel_all_calls == {"BTCUSDT", "ETHUSDT"}
    assert broker.close_calls == ["BTCUSDT"]
    assert events[-1].reason == "test"
    # cancel must be attempted before close for the same symbol
    assert broker.calls.index(("cancel_all", "BTCUSDT")) < broker.calls.index(("close_position", "BTCUSDT"))


async def test_kill_switch_survives_open_order_symbols_failure(st, caplog):
    """A REST timeout fetching open-order symbols must not abort the sweep: the known
    position is still closed, and the event is still published (Important finding 1)."""

    class FailingOrderSymbolsBroker:
        def __init__(self):
            self.cancel_all_calls, self.close_calls = set(), []

        async def positions(self):
            return {"BTCUSDT": make_position(PositionSide.LONG, Decimal("0.002"), Decimal("80000"))}  # noqa: FURB157

        async def open_order_symbols(self):
            raise TimeoutError("rest timeout")

        async def cancel_all(self, s):
            self.cancel_all_calls.add(s)

        async def close_position(self, s):
            self.close_calls.append(s)
            return None  # noqa: PLR1711, RET501

    broker = FailingOrderSymbolsBroker()
    bus = EventBus()
    events = []
    bus.subscribe(KillSwitchTriggered, lambda e: _append(events, e))
    ks = KillSwitch(st, broker, bus)
    await bus.start()
    with caplog.at_level("ERROR", logger="ai_trader.risk.kill_switch"):
        await ks.trigger("rest down")
    await bus.drain()
    await bus.stop()

    assert await ks.is_active()
    assert broker.cancel_all_calls == {"BTCUSDT"}
    assert broker.close_calls == ["BTCUSDT"]
    assert events[-1].reason == "rest down"
    assert any("failed to fetch open order symbols" in r.getMessage() for r in caplog.records)


async def test_kill_switch_closes_position_despite_cancel_all_failure(st):
    """A failed cancel_all for one symbol must not skip close_position for it, and the
    next symbol must still be processed (Important finding 2)."""

    class PartiallyFailingBroker:
        def __init__(self):
            self.cancel_all_calls, self.close_calls = [], []

        async def positions(self):
            return {
                "BTCUSDT": make_position(PositionSide.LONG, Decimal("0.002"), Decimal("80000")),  # noqa: FURB157
                "ETHUSDT": make_position(
                    PositionSide.SHORT, Decimal("0.01"), Decimal("3000"), symbol="ETHUSDT"  # noqa: FURB157
                ),
            }

        async def open_order_symbols(self):
            return set()

        async def cancel_all(self, s):
            self.cancel_all_calls.append(s)
            if s == "BTCUSDT":
                raise RuntimeError("cancel failed")

        async def close_position(self, s):
            self.close_calls.append(s)
            return None  # noqa: PLR1711, RET501

    broker = PartiallyFailingBroker()
    bus = EventBus()
    events = []
    bus.subscribe(KillSwitchTriggered, lambda e: _append(events, e))
    ks = KillSwitch(st, broker, bus)
    await bus.start()
    await ks.trigger("cancel flaky")
    await bus.drain()
    await bus.stop()

    assert await ks.is_active()
    assert set(broker.cancel_all_calls) == {"BTCUSDT", "ETHUSDT"}
    assert set(broker.close_calls) == {"BTCUSDT", "ETHUSDT"}
    assert events[-1].reason == "cancel flaky"
