"""`BinanceFuturesBroker`: the live USDT-M futures broker (design 5.9).

* `submit` validates against the symbol filters before any HTTP call. POST /order is
  never retried; on a timeout / connection error the order is looked up by its
  `client_order_id` instead, so an order that did reach the exchange is never sent twice.
* `start()` opens a listen key, seeds the position cache from `position_risk`, and runs
  the user-data stream plus keepalive (30 min) and reconcile (`reconcile_interval_s`)
  loops as background tasks.
* `reconcile()` compares `position_risk` with the cache; any difference publishes
  `ReconcileMismatch`, optionally invokes `kill(reason)`, and then adopts the remote state.
"""

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Literal, Protocol

import httpx

from ai_trader.bus import EventBus
from ai_trader.exchange.binance.errors import BinanceAPIError, BinanceConnectionError, BinanceError
from ai_trader.exchange.binance.filters import ExchangeInfo
from ai_trader.exchange.binance.parsers import parse_account_update, parse_order_trade_update
from ai_trader.exchange.binance.rest import BinanceFuturesRest
from ai_trader.exchange.binance.ws import BinanceFuturesWS, user_stream_url
from ai_trader.models import (
    AccountState,
    OrderRequest,
    OrderResult,
    OrderType,
    Position,
    PositionSide,
    ReconcileMismatch,
    Side,
    new_client_order_id,
)

log = logging.getLogger(__name__)

KEEPALIVE_INTERVAL_S = 30 * 60


class _WS(Protocol):
    async def run(self) -> None: ...

    async def stop(self) -> None: ...


WSFactory = Callable[[str, Callable[[dict], Awaitable[None]]], _WS]


def _signed(p: Position | None) -> Decimal:
    if p is None:
        return Decimal(0)
    if p.side == PositionSide.SHORT:
        return -p.quantity
    if p.side == PositionSide.LONG:
        return p.quantity
    return Decimal(0)


class BinanceFuturesBroker:
    def __init__(
        self,
        rest: BinanceFuturesRest,
        exchange_info: ExchangeInfo,
        bus: EventBus,
        ws_url: str,
        *,
        ws_factory: WSFactory | None = None,
        reconcile_interval_s: float = 60,
        on_mismatch: Literal["log", "kill"] = "kill",
        kill: Callable[[str], Awaitable[None]] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._rest = rest
        self.exchange_info = exchange_info
        self._bus = bus
        self._ws_url = ws_url
        self._ws_factory: WSFactory = ws_factory or BinanceFuturesWS
        self._reconcile_interval_s = reconcile_interval_s
        self._on_mismatch = on_mismatch
        self._kill = kill
        self._clock = clock
        self._positions: dict[str, Position] = {}
        self._setup_done: set[str] = set()
        self._ws: _WS | None = None
        self._tasks: list[asyncio.Task] = []
        self._listen_key: str | None = None

    # ---- lifecycle --------------------------------------------------------

    async def start(self) -> None:
        self._listen_key = await self._rest.create_listen_key()
        await self.refresh_positions()
        self._ws = self._ws_factory(user_stream_url(self._ws_url, self._listen_key), self._on_user_message)
        self._tasks = [
            asyncio.create_task(self._ws.run(), name="binance-user-stream"),
            asyncio.create_task(self._keepalive_loop(), name="binance-listen-key-keepalive"),
            asyncio.create_task(self._reconcile_loop(), name="binance-reconcile"),
        ]

    async def stop(self) -> None:
        if self._ws is not None:
            try:
                await self._ws.stop()
            except Exception:
                log.exception("stopping the user-data stream failed")
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                try:
                    await task
                except Exception:
                    log.exception("background task %s failed", task.get_name())
        self._tasks = []
        self._ws = None
        if self._listen_key is not None:
            try:
                await self._rest.close_listen_key()
            except (BinanceError, httpx.HTTPError) as exc:
                log.warning("closing the listen key failed: %s", exc)
            self._listen_key = None

    async def _keepalive_loop(self) -> None:
        while True:
            await asyncio.sleep(KEEPALIVE_INTERVAL_S)
            try:
                await self._rest.keepalive_listen_key()
            except (BinanceError, httpx.HTTPError) as exc:
                log.warning("listen key keepalive failed: %s", exc)

    async def _reconcile_loop(self) -> None:
        while True:
            await asyncio.sleep(self._reconcile_interval_s)
            try:
                await self.reconcile()
            except Exception:
                log.exception("position reconcile failed")

    # ---- user-data stream -------------------------------------------------

    async def _on_user_message(self, msg: dict) -> None:
        event = msg.get("e")
        if event == "ORDER_TRADE_UPDATE":
            result, fill = parse_order_trade_update(msg)
            self._bus.publish(result)
            if fill is not None:
                self._bus.publish(fill)
        elif event == "ACCOUNT_UPDATE":
            update = parse_account_update(msg)
            for p in update.state.positions:
                self._set_position(p)
            self._bus.publish(update)
        elif event == "listenKeyExpired":
            log.error("user-data listen key expired; the stream will no longer deliver updates")

    # ---- positions / reconcile --------------------------------------------

    def _set_position(self, p: Position) -> None:
        if p.quantity > 0 and p.side != PositionSide.FLAT:
            self._positions[p.symbol] = p
        else:
            self._positions.pop(p.symbol, None)

    def _adopt(self, remote: list[Position]) -> None:
        self._positions = {}
        for p in remote:
            self._set_position(p)

    async def refresh_positions(self) -> None:
        """Replace the position cache with `positionRisk` from REST. `start()` does this;
        a caller that never starts the user stream (e.g. `ai-trader kill`) calls it directly."""
        self._adopt(await self._rest.position_risk())

    async def reconcile(self) -> None:
        remote = await self._rest.position_risk()
        remote_by_symbol = {p.symbol: p for p in remote if p.quantity > 0 and p.side != PositionSide.FLAT}
        for symbol in sorted(set(self._positions) | set(remote_by_symbol)):
            local_p, remote_p = self._positions.get(symbol), remote_by_symbol.get(symbol)
            local, remote_qty = _signed(local_p), _signed(remote_p)
            if local == remote_qty:
                continue
            self._bus.publish(
                ReconcileMismatch(symbol=symbol, local_qty=abs(local), remote_qty=abs(remote_qty))
            )
            reason = f"reconcile mismatch {symbol}: local {local} remote {remote_qty}"
            log.error(reason)
            if self._on_mismatch == "kill" and self._kill is not None:
                await self._kill(reason)
        self._adopt(remote)

    def positions_snapshot(self) -> dict[str, Position]:
        """The ACCOUNT_UPDATE/reconcile-fed cache; no REST call."""
        return {s: p for s, p in self._positions.items() if p.quantity > 0}

    async def positions(self) -> dict[str, Position]:
        return self.positions_snapshot()

    async def account(self) -> AccountState:
        return await self._rest.account()

    async def open_order_symbols(self) -> set[str]:
        return {o.symbol for o in await self._rest.open_orders()}

    async def ensure_symbol_setup(self, symbol: str, leverage: int, margin_type: str) -> None:
        if symbol in self._setup_done:
            return
        await self._rest.set_margin_type(symbol, margin_type)
        await self._rest.set_leverage(symbol, leverage)
        self._setup_done.add(symbol)

    # ---- orders -----------------------------------------------------------

    async def submit(self, req: OrderRequest) -> OrderResult:
        self.exchange_info.filters_for(req.symbol).validate(req)
        try:
            return await self._rest.place_order(req)
        except (httpx.TimeoutException, BinanceConnectionError) as exc:
            log.warning(
                "place_order %s failed in transport (%s); looking it up before giving up",
                req.client_order_id,
                type(exc).__name__,
            )
            try:
                return await self._rest.get_order(req.symbol, client_order_id=req.client_order_id)
            except (BinanceAPIError, BinanceConnectionError, httpx.TimeoutException) as lookup_exc:
                raise BinanceConnectionError(
                    f"order {req.client_order_id} not confirmed after {type(exc).__name__}: {lookup_exc}"
                ) from exc

    async def cancel(self, symbol: str, client_order_id: str) -> OrderResult:
        return await self._rest.cancel_order(symbol, client_order_id=client_order_id)

    async def cancel_all(self, symbol: str) -> None:
        await self._rest.cancel_all_orders(symbol)

    async def close_position(self, symbol: str) -> OrderResult | None:
        remote = [p for p in await self._rest.position_risk(symbol) if p.symbol == symbol]
        p = next((x for x in remote if x.quantity > 0 and x.side != PositionSide.FLAT), None)
        if p is None:
            self._positions.pop(symbol, None)
            return None
        req = OrderRequest(
            symbol=symbol,
            side=Side.SELL if p.side == PositionSide.LONG else Side.BUY,
            type=OrderType.MARKET,
            quantity=p.quantity,
            reduce_only=True,
            client_order_id=new_client_order_id(),
        )
        return await self.submit(req)
