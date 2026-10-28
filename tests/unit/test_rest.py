# tests/unit/test_rest.py
import json, pathlib  # noqa: I001
from decimal import Decimal
import httpx, pytest, respx
from ai_trader.exchange.binance.errors import BinanceAPIError, BinanceConnectionError, BinanceRateLimitError
from ai_trader.exchange.binance.rest import BinanceFuturesRest
from ai_trader.models import OrderRequest, OrderStatus, OrderType, Side

FX = pathlib.Path(__file__).parents[1] / "fixtures" / "binance"
BASE = "https://testnet.binancefuture.com"
def fx(name): return json.loads((FX / name).read_text())
async def _noop(_s): return None

def test_sign_matches_binance_doc_vector():
    c = BinanceFuturesRest(BASE, "k", "NhqPtmdSJYdKjVHjA7PZj4Mge3R5YNiP1e3UZjInClVN65XAbvqqM6A7H5fATj0j")
    q = "symbol=LTCBTC&side=BUY&type=LIMIT&timeInForce=GTC&quantity=1&price=0.1&recvWindow=5000&timestamp=1499827319559"
    assert c.sign(q) == "c8db56825ae71d6d79447849e617115f4a920fa2acdcab2b053c4b2838bd6b71"

@respx.mock
async def test_exchange_info_filters_non_trading():
    respx.get(f"{BASE}/fapi/v1/exchangeInfo").mock(return_value=httpx.Response(200, json=fx("exchange_info.json")))
    info = await BinanceFuturesRest(BASE).exchange_info()
    assert set(info.symbols) == {"BTCUSDT", "ETHUSDT"}
    assert info.filters_for("BTCUSDT").min_notional == Decimal("100")  # noqa: FURB157

@respx.mock
async def test_place_order_sends_signed_params_and_header():
    route = respx.post(f"{BASE}/fapi/v1/order").mock(return_value=httpx.Response(200, json=fx("order_response.json")))
    c = BinanceFuturesRest(BASE, "KEY", "SECRET", clock=lambda: 1700000000.0)
    req = OrderRequest(symbol="BTCUSDT", side=Side.BUY, type=OrderType.MARKET, quantity=Decimal("0.002"), client_order_id="ait-abc")
    res = await c.place_order(req)
    sent = route.calls.last.request
    assert sent.headers["X-MBX-APIKEY"] == "KEY"
    body = sent.content.decode()
    assert "newClientOrderId=ait-abc" in body and "quantity=0.002" in body and "timestamp=1700000000000" in body
    assert body.split("&")[-1].startswith("signature=")
    assert res.status == OrderStatus.NEW and res.client_order_id == fx("order_response.json")["clientOrderId"]

@respx.mock
async def test_api_error_raises_with_code():
    respx.get(f"{BASE}/fapi/v2/account").mock(return_value=httpx.Response(400, json={"code": -2015, "msg": "Invalid API-key"}))
    with pytest.raises(BinanceAPIError) as ei: await BinanceFuturesRest(BASE, "k", "s").account()
    assert ei.value.code == -2015 and ei.value.status == 400

@respx.mock
async def test_rate_limit_raises_specific_error():
    respx.get(f"{BASE}/fapi/v1/ping").mock(return_value=httpx.Response(429, headers={"Retry-After": "7"}, json={"code": -1003, "msg": "x"}))
    c = BinanceFuturesRest(BASE); c._retry_sleep = _noop
    with pytest.raises(BinanceRateLimitError) as ei: await c.ping()
    assert ei.value.retry_after_s == 7

@respx.mock
async def test_get_retries_on_connect_error_then_succeeds():
    route = respx.get(f"{BASE}/fapi/v1/time")
    route.side_effect = [httpx.ConnectError("x"), httpx.Response(200, json={"serverTime": 1700000001000})]
    c = BinanceFuturesRest(BASE); c._retry_sleep = _noop
    assert await c.server_time() == 1700000001000 and route.call_count == 2

@respx.mock
async def test_post_is_not_retried():
    route = respx.post(f"{BASE}/fapi/v1/order").mock(side_effect=httpx.ConnectError("x"))
    with pytest.raises(BinanceConnectionError):
        await BinanceFuturesRest(BASE, "k", "s").place_order(OrderRequest(symbol="BTCUSDT", side=Side.BUY, type=OrderType.MARKET, quantity=Decimal("0.002"), client_order_id="ait-1"))
    assert route.call_count == 1

@respx.mock
async def test_set_margin_type_swallows_4046():
    respx.post(f"{BASE}/fapi/v1/marginType").mock(return_value=httpx.Response(400, json={"code": -4046, "msg": "No need to change margin type."}))
    await BinanceFuturesRest(BASE, "k", "s").set_margin_type("BTCUSDT", "ISOLATED")

@respx.mock
async def test_position_risk_parses_sides():
    respx.get(f"{BASE}/fapi/v2/positionRisk").mock(return_value=httpx.Response(200, json=fx("position_risk_v2.json")))
    ps = await BinanceFuturesRest(BASE, "k", "s").position_risk()
    by = {p.symbol: p for p in ps}
    assert by["BTCUSDT"].side.value == "SHORT" and by["BTCUSDT"].quantity == Decimal("0.002") and by["ETHUSDT"].side.value == "FLAT"


# ---- additional coverage (not from the brief) ------------------------------


@respx.mock
async def test_rate_limit_is_not_retried():
    route = respx.get(f"{BASE}/fapi/v1/time").mock(return_value=httpx.Response(418, json={"code": -1003, "msg": "banned"}))
    c = BinanceFuturesRest(BASE)
    c._retry_sleep = _noop
    with pytest.raises(BinanceRateLimitError) as ei:
        await c.server_time()
    assert route.call_count == 1 and ei.value.retry_after_s is None


@respx.mock
async def test_get_5xx_retried_three_attempts_then_raises():
    route = respx.get(f"{BASE}/fapi/v1/time").mock(return_value=httpx.Response(503, text="busy"))
    sleeps: list[float] = []

    async def record(s: float) -> None:
        sleeps.append(s)

    c = BinanceFuturesRest(BASE)
    c._retry_sleep = record
    with pytest.raises(BinanceAPIError) as ei:
        await c.server_time()
    assert route.call_count == 3 and sleeps == [0.5, 1.0]
    assert ei.value.status == 503 and ei.value.code == 0 and ei.value.msg == "busy"


@respx.mock
async def test_signed_get_puts_signature_last_in_query():
    route = respx.get(f"{BASE}/fapi/v2/positionRisk").mock(return_value=httpx.Response(200, json=[]))
    c = BinanceFuturesRest(BASE, "k", "s", clock=lambda: 1700000000.0)
    c.time_offset_ms = -500
    await c.position_risk("BTCUSDT")
    query = route.calls.last.request.url.query.decode()
    assert query.startswith("symbol=BTCUSDT&timestamp=1699999999500&recvWindow=5000&signature=")
    unsigned, sig = query.rsplit("&signature=", 1)
    assert sig == c.sign(unsigned)


@respx.mock
async def test_stop_market_close_position_params():
    route = respx.post(f"{BASE}/fapi/v1/order").mock(return_value=httpx.Response(200, json=fx("order_response.json")))
    c = BinanceFuturesRest(BASE, "k", "s")
    req = OrderRequest(symbol="BTCUSDT", side=Side.SELL, type=OrderType.STOP_MARKET,
                       stop_price=Decimal("79000.0"), close_position=True, client_order_id="ait-sl")
    await c.place_order(req)
    body = route.calls.last.request.content.decode()
    assert "stopPrice=79000.0" in body and "closePosition=true" in body and "workingType=MARK_PRICE" in body
    assert "reduceOnly" not in body and "quantity" not in body and "timeInForce" not in body
    assert "newOrderRespType=RESULT" in body


@respx.mock
async def test_limit_order_defaults_gtc():
    route = respx.post(f"{BASE}/fapi/v1/order").mock(return_value=httpx.Response(200, json=fx("order_response.json")))
    c = BinanceFuturesRest(BASE, "k", "s")
    req = OrderRequest(symbol="BTCUSDT", side=Side.BUY, type=OrderType.LIMIT, quantity=Decimal("0.002"),
                       price=Decimal("80000.10"), reduce_only=True, client_order_id="ait-l")
    await c.place_order(req)
    body = route.calls.last.request.content.decode()
    assert "timeInForce=GTC" in body and "price=80000.10" in body and "reduceOnly=true" in body
    assert "workingType" not in body
