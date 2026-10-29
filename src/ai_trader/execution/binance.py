"""`BinanceFuturesBroker`: the live USDT-M futures broker (design 5.9).

* `submit` validates against the symbol filters before any HTTP call. POST /order is
  never retried; on a timeout / connection error the order is looked up by its
  `client_order_id` instead, so an order that did reach the exchange is never sent twice.
  A lookup answering -2013 (does not exist) raises `BinanceOrderNotFound` (the order was
  never placed); any other lookup failure raises `BinanceConnectionError` (unknown).
* `start()` refuses a hedge-mode (dual-side) account, opens a listen key, seeds the
  position cache from `position_risk`, and runs the user-data stream plus keepalive
  (30 min) and reconcile (`reconcile_interval_s`) loops as background tasks. Each runs
  under a small supervisor: if it ends or crashes unexpectedly it is logged at ERROR and
  restarted with backoff.
* Listen-key lifecycle: a `listenKeyExpired` stream event or a failed keepalive rotates
  the key - a new listen key is created, the old stream is stopped and a new one is
  started on the new key. The key itself is never logged.
* `reconcile()` compares `position_risk` with the cache; any difference publishes
  `ReconcileMismatch`, optionally invokes `kill(reason)`, and then adopts the remote state.
"""

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from decimal import Decimal
from typing import Literal, Protocol

import httpx

from ai_trader.bus import EventBus
from ai_trader.exchange.binance.errors import (
    BinanceAPIError,
    BinanceConnectionError,
    BinanceError,
    BinanceOrderNotFound,
)
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
DEFAULT_BACKOFF_S: tuple[float, ...] = (1, 2, 5, 10, 30)
STABLE_RUN_S = 60.0  # a run longer than this resets the backoff schedule
_ORDER_DOES_NOT_EXIST = -2013


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
        keepalive_interval_s: float = KEEPALIVE_INTERVAL_S,
        backoff_s: Sequence[float] = DEFAULT_BACKOFF_S,
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
        self._keepalive_interval_s = keepalive_interval_s
        self._backoff_s = tuple(backoff_s) or DEFAULT_BACKOFF_S
        self._stopping = asyncio.Event()
        self._rotate_lock = asyncio.Lock()
        self._rotations: set[asyncio.Task] = set()

    # ---- lifecycle --------------------------------------------------------

    async def start(self) -> None:
        if await self._rest.position_mode():
            raise SystemExit(
                "hedge (dual-side) position mode is not supported; switch the account to one-way mode"
            )
        self._stopping.clear()
        self._listen_key = await self._rest.create_listen_key()
        await self.refresh_positions()
        self._ws = self._new_ws()
        self._tasks = [
            asyncio.create_task(self._supervise("user-stream", self._run_user_stream), name="binance-user-stream"),
            asyncio.create_task(
                self._supervise("listen-key-keepalive", self._keepalive_loop), name="binance-listen-key-keepalive"
            ),
            asyncio.create_task(self._supervise("reconcile", self._reconcile_loop), name="binance-reconcile"),
        ]

    async def stop(self) -> None:
        self._stopping.set()
        for task in self._rotations:
            task.cancel()
        if self._ws is not None:
            try:
                await self._ws.stop()
            except Exception:
                log.exception("stopping the user-data stream failed")
        tasks = [*self._tasks, *self._rotations]
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                try:
                    await task
                except Exception:
                    log.exception("background task %s failed", task.get_name())
        self._tasks = []
        self._rotations = set()
        self._ws = None
        if self._listen_key is not None:
            try:
                await self._rest.close_listen_key()
            except (BinanceError, httpx.HTTPError) as exc:
                log.warning("closing the listen key failed: %s", exc)
            self._listen_key = None

    def _new_ws(self) -> _WS:
        assert self._listen_key is not None
        return self._ws_factory(user_stream_url(self._ws_url, self._listen_key), self._on_user_message)

    async def _supervise(self, name: str, factory: Callable[[], Awaitable[None]]) -> None:
        """Run `factory()` until stopped; an unexpected return or crash is logged at ERROR
        and the loop restarted with backoff (the same pattern as `App._supervise`)."""
        failures = 0
        while not self._stopping.is_set():
            started = time.monotonic()
            try:
                await factory()
            except asyncio.CancelledError:
                raise
            except Exception:
                if self._stopping.is_set():
                    return
                log.exception("binance %s crashed; restarting", name)
            else:
                if self._stopping.is_set():
                    return
                log.error("binance %s ended unexpectedly; restarting", name)
            if time.monotonic() - started > STABLE_RUN_S:
                failures = 0
            delay = self._backoff_s[min(failures, len(self._backoff_s) - 1)]
            failures += 1
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stopping.wait(), timeout=delay)

    async def _run_user_stream(self) -> None:
        """Run the current user-data stream; a stream stopped by a key rotation hands over
        to its replacement immediately. Any other end returns (or raises) to the
        supervisor, which restarts on a fresh connection object."""
        while not self._stopping.is_set():
            ws = self._ws
            if ws is None:
                return
            try:
                await ws.run()
            except Exception:
                if self._ws is ws:
                    self._ws = self._new_ws()
                raise
            if self._stopping.is_set():
                return
            if self._ws is not ws:
                continue  # rotated: run the replacement
            self._ws = self._new_ws()
            return

    async def _keepalive_loop(self) -> None:
        while not self._stopping.is_set():
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stopping.wait(), timeout=self._keepalive_interval_s)
            if self._stopping.is_set():
                return
            try:
                await self._rest.keepalive_listen_key()
            except Exception as exc:  # noqa: BLE001 - any failure may mean a dead key: rotate
                log.warning("listen key keepalive failed (%s); rotating the listen key", type(exc).__name__)
                try:
                    await self._rotate_listen_key("keepalive failed")
                except Exception:
                    log.exception("listen key rotation failed; retrying at the next keepalive")

    async def _rotate_listen_key(self, reason: str) -> None:
        """New listen key -> stop the old stream -> start one on the new key (the user-stream
        supervisor picks it up). Serialised by a lock."""
        async with self._rotate_lock:
            if self._stopping.is_set():
                return
            log.warning("rotating the user-data listen key: %s", reason)
            self._listen_key = await self._rest.create_listen_key()
            old, self._ws = self._ws, self._new_ws()
            if old is not None:
                try:
                    await old.stop()
                except Exception:
                    log.exception("stopping the old user-data stream failed")
            log.info("user-data stream restarted on a new listen key")

    def _spawn_rotation(self, reason: str) -> None:
        # Not awaited inline: the caller is the old stream's own message handler, which
        # the rotation stops.
        task = asyncio.create_task(self._rotate_with_retry(reason), name="binance-listen-key-rotate")
        self._rotations.add(task)
        task.add_done_callback(self._rotations.discard)

    async def _rotate_with_retry(self, reason: str) -> None:
        """Rotate, retrying with backoff (`backoff_s`, the last delay repeating) until it
        works or the broker stops: an expired key must not wait 30 min for the keepalive."""
        attempt = 0
        while not self._stopping.is_set():
            try:
                await self._rotate_listen_key(reason)
                return
            except Exception:
                delay = self._backoff_s[min(attempt, len(self._backoff_s) - 1)]
                log.exception("listen key rotation failed; retrying in %.0f s", delay)
            attempt += 1
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stopping.wait(), timeout=delay)

    async def _reconcile_loop(self) -> None:
        while not self._stopping.is_set():
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stopping.wait(), timeout=self._reconcile_interval_s)
            if self._stopping.is_set():
                return
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
            log.error("user-data listen key expired; rotating to a new listen key")
            self._spawn_rotation("listenKeyExpired")

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
            except BinanceAPIError as lookup_exc:
                if lookup_exc.code == _ORDER_DOES_NOT_EXIST:
                    raise BinanceOrderNotFound(
                        f"order {req.client_order_id} does not exist after {type(exc).__name__}"
                    ) from exc
                raise BinanceConnectionError(
                    f"order {req.client_order_id} not confirmed after {type(exc).__name__}: {lookup_exc}"
                ) from exc
            except (BinanceConnectionError, httpx.TimeoutException) as lookup_exc:
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
