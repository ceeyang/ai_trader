from decimal import Decimal

import httpx
import pytest
import respx
from conftest import _append, fake_ws_factory, fx

from ai_trader.exchange.binance.errors import BinanceConnectionError, FilterViolation
from ai_trader.exchange.binance.rest import BinanceFuturesRest
from ai_trader.execution.binance import BinanceFuturesBroker
from ai_trader.models import (
    AccountUpdate,
    Fill,
    OrderRequest,
    OrderResult,
    OrderStatus,
    OrderType,
    PositionSide,
    ReconcileMismatch,
    Side,
)

BASE = "https://testnet.binancefuture.com"


def _req(cid: str = "ait-abc", qty: str = "0.002") -> OrderRequest:
    return OrderRequest(
        symbol="BTCUSDT", side=Side.BUY, type=OrderType.MARKET, quantity=Decimal(qty), client_order_id=cid
    )


def _broker(bus, exchange_info, **kw) -> BinanceFuturesBroker:
    return BinanceFuturesBroker(
        BinanceFuturesRest(BASE, "k", "s"), exchange_info, bus, "wss://x", ws_factory=fake_ws_factory, **kw
    )


@respx.mock
async def test_submit_timeout_then_found_does_not_resend(bus, exchange_info):
    post = respx.post(f"{BASE}/fapi/v1/order").mock(side_effect=httpx.ReadTimeout("t"))
    get = respx.get(f"{BASE}/fapi/v1/order").mock(return_value=httpx.Response(200, json=fx("order_response.json") | {"clientOrderId": "ait-abc", "status": "FILLED"}))
    br = BinanceFuturesBroker(BinanceFuturesRest(BASE, "k", "s"), exchange_info, bus, "wss://x", ws_factory=fake_ws_factory)
    res = await br.submit(OrderRequest(symbol="BTCUSDT", side=Side.BUY, type=OrderType.MARKET, quantity=Decimal("0.002"), client_order_id="ait-abc"))
    assert res.status == OrderStatus.FILLED and post.call_count == 1 and get.call_count == 1
    assert "origClientOrderId=ait-abc" in str(get.calls.last.request.url)


@respx.mock
async def test_submit_timeout_and_not_found_raises(bus, exchange_info):
    post = respx.post(f"{BASE}/fapi/v1/order").mock(side_effect=httpx.ReadTimeout("t"))
    respx.get(f"{BASE}/fapi/v1/order").mock(return_value=httpx.Response(400, json={"code": -2013, "msg": "Order does not exist."}))
    br = _broker(bus, exchange_info)
    with pytest.raises(BinanceConnectionError):
        await br.submit(_req())
    assert post.call_count == 1


@respx.mock
async def test_submit_success_returns_result(bus, exchange_info):
    respx.post(f"{BASE}/fapi/v1/order").mock(
        return_value=httpx.Response(200, json=fx("order_response.json") | {"clientOrderId": "ait-ok"})
    )
    res = await _broker(bus, exchange_info).submit(_req("ait-ok"))
    assert res.client_order_id == "ait-ok" and res.status == OrderStatus.NEW


async def test_submit_validates_filters_first(bus, exchange_info):
    br = _broker(bus, exchange_info)
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(f"{BASE}/fapi/v1/order").mock(return_value=httpx.Response(200, json={}))
        with pytest.raises(FilterViolation):
            await br.submit(OrderRequest(symbol="BTCUSDT", side=Side.BUY, type=OrderType.MARKET, quantity=Decimal("0.0015"), client_order_id="ait-z"))
        assert route.call_count == 0


@respx.mock
async def test_user_stream_fill_published_and_positions_updated(bus, exchange_info):
    respx.post(f"{BASE}/fapi/v1/listenKey").mock(return_value=httpx.Response(200, json={"listenKey": "LK"}))
    respx.get(f"{BASE}/fapi/v2/positionRisk").mock(return_value=httpx.Response(200, json=[]))
    close_lk = respx.delete(f"{BASE}/fapi/v1/listenKey").mock(return_value=httpx.Response(200, json={}))
    fills = []; bus.subscribe(Fill, lambda e: _append(fills, e)); await bus.start()
    results: list[OrderResult] = []
    updates: list[AccountUpdate] = []
    bus.subscribe(OrderResult, lambda e: _append(results, e))
    bus.subscribe(AccountUpdate, lambda e: _append(updates, e))
    br = BinanceFuturesBroker(BinanceFuturesRest(BASE, "k", "s"), exchange_info, bus, "wss://x", ws_factory=fake_ws_factory); await br.start()
    h = fake_ws_factory.handlers["wss://x/ws/LK"]
    await h(fx("ws_order_trade_update_fill.json")); await h(fx("ws_account_update.json")); await bus.drain()
    assert fills[0].client_order_id == "ait-abc" and (await br.positions())["BTCUSDT"].quantity == Decimal("0.002")
    assert results[0].client_order_id == "ait-abc" and results[0].status == OrderStatus.FILLED
    assert updates[0].state.total_wallet_balance == Decimal("10001.2")
    assert br.positions_snapshot() == await br.positions() and "BTCUSDT" in br.positions_snapshot()
    await br.stop()
    assert close_lk.call_count == 1


@respx.mock
async def test_reconcile_mismatch_triggers_kill(bus, exchange_info):
    respx.get(f"{BASE}/fapi/v2/positionRisk").mock(return_value=httpx.Response(200, json=fx("position_risk_v2.json")))  # 远端 BTC 空 0.002
    killed = []; events = []; bus.subscribe(ReconcileMismatch, lambda e: _append(events, e)); await bus.start()
    async def kill(reason): killed.append(reason)  # noqa: E704
    br = BinanceFuturesBroker(BinanceFuturesRest(BASE, "k", "s"), exchange_info, bus, "wss://x", ws_factory=fake_ws_factory, kill=kill)
    await br.reconcile(); await bus.drain()
    assert events[-1].symbol == "BTCUSDT" and events[-1].remote_qty == Decimal("0.002") and killed and "BTCUSDT" in killed[0]
    assert len(events) == 1 and events[0].local_qty == Decimal(0)
    pos = (await br.positions())["BTCUSDT"]
    assert pos.side == PositionSide.SHORT and pos.quantity == Decimal("0.002")
    # remote state was adopted: a second pass finds nothing to report
    await br.reconcile(); await bus.drain()
    assert len(events) == 1 and len(killed) == 1


@respx.mock
async def test_reconcile_mismatch_log_mode_does_not_kill(bus, exchange_info):
    respx.get(f"{BASE}/fapi/v2/positionRisk").mock(return_value=httpx.Response(200, json=fx("position_risk_v2.json")))
    killed: list[str] = []

    async def kill(reason):
        killed.append(reason)

    events: list[ReconcileMismatch] = []
    bus.subscribe(ReconcileMismatch, lambda e: _append(events, e))
    br = _broker(bus, exchange_info, kill=kill, on_mismatch="log")
    await br.reconcile()
    await bus.drain()
    assert len(events) == 1 and killed == []


@respx.mock
async def test_ensure_symbol_setup_once_per_symbol(bus, exchange_info):
    margin = respx.post(f"{BASE}/fapi/v1/marginType").mock(return_value=httpx.Response(200, json={"code": 200}))
    lev = respx.post(f"{BASE}/fapi/v1/leverage").mock(
        return_value=httpx.Response(200, json={"leverage": 2, "symbol": "BTCUSDT"})
    )
    br = _broker(bus, exchange_info)
    await br.ensure_symbol_setup("BTCUSDT", 2, "ISOLATED")
    await br.ensure_symbol_setup("BTCUSDT", 2, "ISOLATED")
    assert margin.call_count == 1 and lev.call_count == 1


@respx.mock
async def test_close_position_and_open_order_symbols(bus, exchange_info):
    respx.get(f"{BASE}/fapi/v2/positionRisk").mock(return_value=httpx.Response(200, json=fx("position_risk_v2.json")))
    post = respx.post(f"{BASE}/fapi/v1/order").mock(
        return_value=httpx.Response(200, json=fx("order_response.json") | {"status": "FILLED"})
    )
    respx.get(f"{BASE}/fapi/v1/openOrders").mock(
        return_value=httpx.Response(200, json=[fx("order_response.json")])
    )
    br = _broker(bus, exchange_info)
    res = await br.close_position("BTCUSDT")
    assert res is not None and res.status == OrderStatus.FILLED
    body = post.calls.last.request.content.decode()
    assert "side=BUY" in body and "reduceOnly=true" in body and "quantity=0.002" in body
    assert await br.close_position("ETHUSDT") is None
    assert post.call_count == 1
    assert await br.open_order_symbols() == {"BTCUSDT"}


@respx.mock
async def test_refresh_positions_without_start(bus, exchange_info):
    respx.get(f"{BASE}/fapi/v2/positionRisk").mock(return_value=httpx.Response(200, json=fx("position_risk_v2.json")))
    br = BinanceFuturesBroker(BinanceFuturesRest(BASE, "k", "s"), exchange_info, bus, "wss://x", ws_factory=fake_ws_factory)
    assert br.positions_snapshot() == {}
    await br.refresh_positions()
    assert br.positions_snapshot()["BTCUSDT"].quantity == Decimal("0.002")
