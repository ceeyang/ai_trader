"""Async REST client for Binance USDT-M futures (design 5.4)."""

import asyncio
import hashlib
import hmac
import logging
import time
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

import httpx

from ai_trader.exchange.binance.errors import (
    BinanceAPIError,
    BinanceConnectionError,
    BinanceError,
    BinanceRateLimitError,
)
from ai_trader.exchange.binance.filters import ExchangeInfo
from ai_trader.exchange.binance.parsers import (
    parse_exchange_info,
    parse_rest_account,
    parse_rest_kline,
    parse_rest_order,
    parse_rest_position,
    parse_rest_premium_index,
)
from ai_trader.models import AccountState, Kline, MarkPrice, OrderRequest, OrderResult, OrderType, Position

log = logging.getLogger(__name__)

_RETRY_BACKOFF_S = (0.5, 1.0, 2.0)
_MAX_ATTEMPTS = 3
_MARGIN_TYPE_UNCHANGED = -4046
_TRIGGER_TYPES = {OrderType.STOP_MARKET, OrderType.TAKE_PROFIT_MARKET}


def _fmt(value: Decimal) -> str:
    return format(value, "f")


def _retry_after(resp: httpx.Response) -> float | None:
    value = resp.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _api_error(resp: httpx.Response) -> BinanceAPIError:
    code, msg = 0, resp.text
    try:
        payload = resp.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        code = int(payload.get("code", 0))
        msg = str(payload.get("msg", msg))
    if resp.status_code in (418, 429):
        return BinanceRateLimitError(resp.status_code, code, msg, _retry_after(resp))
    return BinanceAPIError(resp.status_code, code, msg)


class BinanceFuturesRest:
    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        api_secret: str | None = None,
        *,
        recv_window_ms: int = 5000,
        timeout_s: float = 10.0,
        http: httpx.AsyncClient | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._api_secret = api_secret
        self._recv_window_ms = recv_window_ms
        self._owns_http = http is None
        self._http = http if http is not None else httpx.AsyncClient(timeout=timeout_s)
        self._clock = clock
        self._retry_sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
        self.time_offset_ms: int = 0

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    # ---- plumbing -------------------------------------------------------

    def sign(self, query: str) -> str:
        if not self._api_secret:
            raise BinanceError("api_secret is required for signed requests")
        return hmac.new(self._api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()

    def _now_ms(self) -> int:
        return int(self._clock() * 1000) + self.time_offset_ms

    def _encode(self, params: dict[str, Any], signed: bool) -> str:
        if not signed:
            return urlencode(params)
        full = dict(params)
        full["timestamp"] = self._now_ms()
        full["recvWindow"] = self._recv_window_ms
        query = urlencode(full)
        return f"{query}&signature={self.sign(query)}"

    async def _send(self, method: str, path: str, query: str) -> httpx.Response:
        headers: dict[str, str] = {}
        if self._api_key:
            headers["X-MBX-APIKEY"] = self._api_key
        url = f"{self._base_url}{path}"
        if method in ("GET", "DELETE"):
            if query:
                url = f"{url}?{query}"
            return await self._http.request(method, url, headers=headers)
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        return await self._http.request(method, url, headers=headers, content=query.encode())

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        signed: bool,
        retry: bool,
    ) -> Any:
        params = params or {}
        attempts = _MAX_ATTEMPTS if retry else 1
        for attempt in range(attempts):
            last = attempt == attempts - 1
            query = self._encode(params, signed)  # fresh timestamp on every attempt
            try:
                resp = await self._send(method, path, query)
            except httpx.TransportError as exc:
                log.warning("%s %s transport error: %s", method, path, type(exc).__name__)
                if last:
                    raise BinanceConnectionError(f"{method} {path}: {type(exc).__name__}") from exc
                await self._retry_sleep(_RETRY_BACKOFF_S[attempt])
                continue
            log.debug("%s %s -> %s", method, path, resp.status_code)
            if resp.status_code >= 500 and not last:
                log.warning("%s %s -> %s, retrying", method, path, resp.status_code)
                await self._retry_sleep(_RETRY_BACKOFF_S[attempt])
                continue
            if not resp.is_success:
                raise _api_error(resp)
            return resp.json() if resp.content else {}
        raise AssertionError("unreachable")  # pragma: no cover

    def _require_key(self) -> None:
        if not self._api_key:
            raise BinanceError("api_key is required for this endpoint")

    # ---- market data (public) ---------------------------------------------

    async def ping(self) -> None:
        await self._request("GET", "/fapi/v1/ping", signed=False, retry=True)

    async def server_time(self) -> int:
        data = await self._request("GET", "/fapi/v1/time", signed=False, retry=True)
        return int(data["serverTime"])

    async def sync_time(self) -> int:
        server = await self.server_time()
        self.time_offset_ms = server - int(self._clock() * 1000)
        return self.time_offset_ms

    async def exchange_info(self) -> ExchangeInfo:
        data = await self._request("GET", "/fapi/v1/exchangeInfo", signed=False, retry=True)
        return parse_exchange_info(data)

    async def premium_index(self, symbol: str) -> MarkPrice:
        data = await self._request(
            "GET", "/fapi/v1/premiumIndex", {"symbol": symbol}, signed=False, retry=True
        )
        return parse_rest_premium_index(data)

    async def klines(
        self,
        symbol: str,
        interval: str,
        limit: int = 500,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> list[Kline]:
        """`start_time` / `end_time` are epoch milliseconds."""
        params: dict[str, Any] = {"symbol": symbol, "interval": interval, "limit": limit}
        if start_time is not None:
            params["startTime"] = start_time
        if end_time is not None:
            params["endTime"] = end_time
        rows = await self._request("GET", "/fapi/v1/klines", params, signed=False, retry=True)
        return [parse_rest_kline(r, symbol=symbol, interval=interval) for r in rows]

    async def open_interest(self, symbol: str) -> Decimal:
        data = await self._request(
            "GET", "/fapi/v1/openInterest", {"symbol": symbol}, signed=False, retry=True
        )
        return Decimal(str(data["openInterest"]))

    # ---- account (signed) ---------------------------------------------------

    async def account(self) -> AccountState:
        data = await self._request("GET", "/fapi/v2/account", signed=True, retry=True)
        return parse_rest_account(data)

    async def position_risk(self, symbol: str | None = None) -> list[Position]:
        params = {"symbol": symbol} if symbol else {}
        data = await self._request("GET", "/fapi/v2/positionRisk", params, signed=True, retry=True)
        return [parse_rest_position(p) for p in data]

    async def set_leverage(self, symbol: str, leverage: int) -> int:
        data = await self._request(
            "POST", "/fapi/v1/leverage", {"symbol": symbol, "leverage": leverage}, signed=True, retry=False
        )
        return int(data["leverage"])

    async def set_margin_type(self, symbol: str, margin_type: str) -> None:
        try:
            await self._request(
                "POST",
                "/fapi/v1/marginType",
                {"symbol": symbol, "marginType": margin_type},
                signed=True,
                retry=False,
            )
        except BinanceAPIError as exc:
            if exc.code != _MARGIN_TYPE_UNCHANGED:
                raise

    # ---- orders (signed) ------------------------------------------------------

    @staticmethod
    def _order_params(req: OrderRequest) -> dict[str, Any]:
        params: dict[str, Any] = {"symbol": req.symbol, "side": req.side.value, "type": req.type.value}
        tif = req.time_in_force or ("GTC" if req.type == OrderType.LIMIT else None)
        if tif is not None:
            params["timeInForce"] = tif
        if req.quantity is not None:
            params["quantity"] = _fmt(req.quantity)
        if req.price is not None:
            params["price"] = _fmt(req.price)
        if req.stop_price is not None:
            params["stopPrice"] = _fmt(req.stop_price)
        # Only sent when set: Binance rejects reduceOnly alongside closePosition.
        if req.reduce_only:
            params["reduceOnly"] = "true"
        if req.close_position:
            params["closePosition"] = "true"
        params["newClientOrderId"] = req.client_order_id
        if req.type in _TRIGGER_TYPES:
            params["workingType"] = "MARK_PRICE"
        params["newOrderRespType"] = "RESULT"
        return params

    async def place_order(self, req: OrderRequest) -> OrderResult:
        """POST /fapi/v1/order. Never retried automatically."""
        data = await self._request("POST", "/fapi/v1/order", self._order_params(req), signed=True, retry=False)
        return parse_rest_order(data)

    @staticmethod
    def _order_ref(symbol: str, client_order_id: str | None, order_id: int | None) -> dict[str, Any]:
        params: dict[str, Any] = {"symbol": symbol}
        if order_id is not None:
            params["orderId"] = order_id
        elif client_order_id is not None:
            params["origClientOrderId"] = client_order_id
        else:
            raise ValueError("client_order_id or order_id is required")
        return params

    async def get_order(
        self, symbol: str, *, client_order_id: str | None = None, order_id: int | None = None
    ) -> OrderResult:
        params = self._order_ref(symbol, client_order_id, order_id)
        data = await self._request("GET", "/fapi/v1/order", params, signed=True, retry=True)
        return parse_rest_order(data)

    async def cancel_order(
        self, symbol: str, *, client_order_id: str | None = None, order_id: int | None = None
    ) -> OrderResult:
        params = self._order_ref(symbol, client_order_id, order_id)
        data = await self._request("DELETE", "/fapi/v1/order", params, signed=True, retry=False)
        return parse_rest_order(data)

    async def cancel_all_orders(self, symbol: str) -> None:
        await self._request("DELETE", "/fapi/v1/allOpenOrders", {"symbol": symbol}, signed=True, retry=False)

    async def open_orders(self, symbol: str | None = None) -> list[OrderResult]:
        params = {"symbol": symbol} if symbol else {}
        data = await self._request("GET", "/fapi/v1/openOrders", params, signed=True, retry=True)
        return [parse_rest_order(o) for o in data]

    # ---- user data stream (API key, unsigned) -------------------------------

    async def create_listen_key(self) -> str:
        self._require_key()
        data = await self._request("POST", "/fapi/v1/listenKey", signed=False, retry=False)
        return str(data["listenKey"])

    async def keepalive_listen_key(self) -> None:
        self._require_key()
        await self._request("PUT", "/fapi/v1/listenKey", signed=False, retry=False)

    async def close_listen_key(self) -> None:
        self._require_key()
        await self._request("DELETE", "/fapi/v1/listenKey", signed=False, retry=False)
