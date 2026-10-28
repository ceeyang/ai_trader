import json
from decimal import Decimal

from conftest import make_mark_price, make_order_record

from ai_trader.execution.paper import PAPER_STATE_KV_KEY, PaperBroker
from ai_trader.models import OrderRequest, OrderRole, OrderStatus, OrderType, PositionSide, Side


def _sl(cid: str = "ait-sl", stop: Decimal = Decimal(79000)) -> OrderRequest:
    return OrderRequest(
        symbol="BTCUSDT", side=Side.SELL, type=OrderType.STOP_MARKET,
        stop_price=stop, close_position=True, client_order_id=cid,
    )


def _tp(cid: str = "ait-tp", stop: Decimal = Decimal(82000)) -> OrderRequest:
    return OrderRequest(
        symbol="BTCUSDT", side=Side.SELL, type=OrderType.TAKE_PROFIT_MARKET,
        stop_price=stop, close_position=True, client_order_id=cid,
    )


def _entry(cid: str = "ait-entry", qty: Decimal = Decimal("0.002")) -> OrderRequest:
    return OrderRequest(symbol="BTCUSDT", side=Side.BUY, type=OrderType.MARKET, quantity=qty, client_order_id=cid)


async def _open_protected(st, bus, state, exchange_info) -> PaperBroker:
    state.update_mark(make_mark_price(mark=Decimal(80000)))
    pb = PaperBroker(state, bus, exchange_info, store=st)
    await pb.start()
    await pb.submit(_entry())
    for req, role in ((_sl(), OrderRole.STOP_LOSS), (_tp(), OrderRole.TAKE_PROFIT)):
        await pb.submit(req)
        rec = make_order_record(req.client_order_id, role=role, status=OrderStatus.NEW)
        await st.upsert_order(rec)
    return pb


async def test_paper_state_round_trips_through_store(st, bus, state, exchange_info):
    pb = await _open_protected(st, bus, state, exchange_info)
    # a protective row left open in the DB by an earlier (now gone) process
    await st.upsert_order(make_order_record("ait-stale", role=OrderRole.STOP_LOSS, status=OrderStatus.NEW))
    await st.upsert_order(make_order_record("ait-stale-eth", role=OrderRole.TAKE_PROFIT,
                                            status=OrderStatus.NEW, symbol="ETHUSDT"))

    pb2 = PaperBroker(state, bus, exchange_info, store=st)
    await pb2.start()

    assert pb2.wallet_balance == pb.wallet_balance and pb2.wallet_balance < Decimal(10000)
    assert pb2.realized_pnl == pb.realized_pnl
    assert pb2.positions_snapshot() == pb.positions_snapshot()
    pos = pb2.positions_snapshot()["BTCUSDT"]
    assert pos.side == PositionSide.LONG and pos.quantity == Decimal("0.002") and pos.entry_price == Decimal("80016.00")
    assert pb2._pending == pb._pending and set(pb2._pending) == {"ait-sl", "ait-tp"}
    assert await pb2.open_order_symbols() == {"BTCUSDT"}
    # order ids keep counting from where the first broker stopped
    assert (await pb2.submit(_sl("ait-sl2"))).order_id == 4

    assert (await st.get_order("ait-stale")).status == OrderStatus.CANCELED
    assert (await st.get_order("ait-stale-eth")).status == OrderStatus.CANCELED
    assert (await st.get_order("ait-sl")).status == OrderStatus.NEW
    assert (await st.get_order("ait-tp")).status == OrderStatus.NEW


async def test_restored_pending_order_still_triggers(st, bus, state, exchange_info):
    await _open_protected(st, bus, state, exchange_info)
    pb2 = PaperBroker(state, bus, exchange_info, store=st)
    await bus.start()
    await pb2.start()
    bus.publish(make_mark_price(mark=Decimal(78990)))
    await bus.drain()
    assert pb2.positions_snapshot() == {}
    assert set(pb2._pending) == {"ait-tp"}
    # the trigger itself was persisted
    pb3 = PaperBroker(state, bus, exchange_info, store=st)
    await pb3.start()
    assert pb3.positions_snapshot() == {} and set(pb3._pending) == {"ait-tp"}
    assert pb3.wallet_balance == pb2.wallet_balance


async def test_cancel_and_cancel_all_are_persisted(st, bus, state, exchange_info):
    pb = await _open_protected(st, bus, state, exchange_info)
    await pb.cancel("BTCUSDT", "ait-sl")
    snap = json.loads(await st.get_kv(PAPER_STATE_KV_KEY))
    assert [p["request"]["client_order_id"] for p in snap["pending"]] == ["ait-tp"]
    await pb.cancel_all("BTCUSDT")
    pb2 = PaperBroker(state, bus, exchange_info, store=st)
    await pb2.start()
    assert pb2._pending == {}
    assert pb2.positions_snapshot()["BTCUSDT"].quantity == Decimal("0.002")


async def test_close_position_is_persisted(st, bus, state, exchange_info):
    pb = await _open_protected(st, bus, state, exchange_info)
    await pb.cancel_all("BTCUSDT")
    await pb.close_position("BTCUSDT")
    pb2 = PaperBroker(state, bus, exchange_info, store=st)
    await pb2.start()
    assert pb2.positions_snapshot() == {} and pb2.wallet_balance == pb.wallet_balance


async def test_state_json_uses_decimal_strings(st, bus, state, exchange_info):
    await _open_protected(st, bus, state, exchange_info)
    snap = json.loads(await st.get_kv(PAPER_STATE_KV_KEY))
    assert isinstance(snap["wallet_balance"], str) and isinstance(snap["realized_pnl"], str)
    assert snap["positions"]["BTCUSDT"] == {"qty": "0.002", "entry_price": "80016.00"}
    assert snap["next_order_id"] == 4
    assert Decimal(snap["pending"][0]["request"]["stop_price"]) == Decimal(79000)


async def test_fresh_store_starts_from_initial_balance_and_cancels_orphans(st, bus, state, exchange_info):
    await st.upsert_order(make_order_record("ait-old", role=OrderRole.STOP_LOSS, status=OrderStatus.NEW))
    await st.upsert_order(make_order_record("ait-entry-old", role=OrderRole.ENTRY, status=OrderStatus.NEW))
    pb = PaperBroker(state, bus, exchange_info, store=st, initial_balance=Decimal(5000))
    await pb.start()
    assert pb.wallet_balance == Decimal(5000) and pb.positions_snapshot() == {}
    assert (await st.get_order("ait-old")).status == OrderStatus.CANCELED
    assert (await st.get_order("ait-entry-old")).status == OrderStatus.NEW  # only protective rows


async def test_without_store_nothing_is_persisted(st, bus, state, exchange_info):
    state.update_mark(make_mark_price(mark=Decimal(80000)))
    pb = PaperBroker(state, bus, exchange_info)
    await pb.start()
    await pb.submit(_entry())
    assert await st.get_kv(PAPER_STATE_KV_KEY) is None
