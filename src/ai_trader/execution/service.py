"""`ExecutionService`: turns approved `Decision`s into broker orders (design 5.9).

Every decision goes through `risk.evaluate` first; nothing reaches `broker.submit`
unless the verdict approves it.

* OPEN: symbol setup -> quantity from the (possibly risk-adjusted) notional at the
  current mark -> MARKET entry -> once filled, a `close_position` STOP_MARKET /
  TAKE_PROFIT_MARKET pair on the opposite side, priced off the entry's average price and
  rounded down to the tick. The pair is placed right away when `submit` returns FILLED
  (paper, or a live RESULT response), otherwise when the entry's FILLED `OrderResult`
  arrives on the bus — whichever comes first, exactly once.
* CLOSE: `cancel_all(symbol)` then `close_position(symbol)`.
* `Fill`s are persisted; `OrderResult`s update order status. A protective order that
  fills (seen as either its `Fill` or its FILLED `OrderResult`) cancels its sibling.
* `enforce_max_hold()` (every 60 s from `run()`) publishes a CLOSE decision for any
  position held at least its decision's `max_hold_s` — except while the kill switch
  (kv `kill_switch`) is active: the risk engine would reject those CLOSEs anyway and the
  kill switch's own sweep does the flattening.
"""

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol

import httpx

from ai_trader.bus import EventBus
from ai_trader.data.market_state import MarketState
from ai_trader.exchange.binance.errors import BinanceAPIError, BinanceConnectionError, FilterViolation
from ai_trader.execution.broker import Broker
from ai_trader.execution.paper import PaperBrokerError
from ai_trader.models import (
    AccountState,
    Decision,
    Fill,
    Intent,
    OrderRecord,
    OrderRequest,
    OrderResult,
    OrderRole,
    OrderStatus,
    OrderType,
    PositionSide,
    RiskVerdict,
    Side,
    new_client_order_id,
    new_id,
)
from ai_trader.settings import Settings
from ai_trader.storage.db import Store

log = logging.getLogger(__name__)

MAX_HOLD_CHECK_INTERVAL_S = 60
_PROTECTIVE_ROLES = {OrderRole.STOP_LOSS, OrderRole.TAKE_PROFIT}
_UNKNOWN_ORDER = -2011  # Binance: cancel of an order that no longer exists
# Transport failures after which the order may still exist (and fill) on the exchange.
_UNCONFIRMED = (BinanceConnectionError, httpx.TimeoutException)


class _Risk(Protocol):
    async def evaluate(self, d: Decision, account: AccountState) -> RiskVerdict: ...


@dataclass(frozen=True)
class _Held:
    entered_at: float
    max_hold_s: int


def _opposite(side: Side) -> Side:
    return Side.SELL if side == Side.BUY else Side.BUY


class ExecutionService:
    def __init__(
        self,
        bus: EventBus,
        broker: Broker,
        risk: _Risk,
        store: Store,
        settings: Settings,
        *,
        state: MarketState,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._bus = bus
        self._broker = broker
        self._risk = risk
        self._store = store
        self._settings = settings
        self._state = state
        self._clock = clock
        self._entry_time: dict[str, _Held] = {}
        self._awaiting_fill: dict[str, Decision] = {}  # entry client_order_id -> decision
        self._sibling_handled: set[str] = set()  # protective client_order_ids already acted on
        self._stop = asyncio.Event()

    # ---- lifecycle --------------------------------------------------------

    async def start(self) -> None:
        # Positions that already exist at start-up (restored paper state, or live positions
        # left from before a restart) never went through `_on_entry_filled`: track them for
        # max-hold from now, with the configured `max_hold_s`.
        now = self._clock()
        for symbol in self._broker.positions_snapshot():
            if symbol not in self._entry_time:
                self._entry_time[symbol] = _Held(entered_at=now, max_hold_s=self._settings.strategy.max_hold_s)
                log.info("tracking pre-existing %s position for max hold (%ss from now)",
                         symbol, self._settings.strategy.max_hold_s)
        self._bus.subscribe(Decision, self.handle_decision)
        self._bus.subscribe(Fill, self.on_fill)
        self._bus.subscribe(OrderResult, self.on_order_result)

    async def run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.enforce_max_hold()
            except Exception:
                log.exception("max-hold check failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=MAX_HOLD_CHECK_INTERVAL_S)

    async def stop(self) -> None:
        self._stop.set()

    # ---- decisions --------------------------------------------------------

    async def handle_decision(self, d: Decision) -> None:
        account = await self._broker.account()
        verdict = await self._risk.evaluate(d, account)
        if not verdict.approved:
            log.info("decision %s %s %s rejected by risk: %s", d.id, d.intent.value, d.symbol, verdict.reason)
            return
        if d.intent == Intent.OPEN:
            await self._open(d, verdict)
        else:
            await self._close(d)

    async def _open(self, d: Decision, verdict: RiskVerdict) -> None:
        symbol = d.symbol
        await self._broker.ensure_symbol_setup(symbol, self._settings.leverage, self._settings.margin_type)
        notional = verdict.adjusted_notional if verdict.adjusted_notional is not None else d.notional_usdt
        mp = self._state.mark(symbol)
        if mp is None:
            log.warning("no mark price for %s; skipping OPEN decision %s", symbol, d.id)
            return
        filters = self._broker.exchange_info.filters_for(symbol)
        try:
            qty = filters.qty_for_notional(notional, mp.mark_price)
        except FilterViolation as exc:
            log.warning("FilterViolation for OPEN decision %s on %s: %s", d.id, symbol, exc)
            return
        req = OrderRequest(
            symbol=symbol,
            side=d.side,
            type=OrderType.MARKET,
            quantity=qty,
            client_order_id=new_client_order_id(),
        )
        self._awaiting_fill[req.client_order_id] = d
        try:
            res = await self._submit_recorded(req, OrderRole.ENTRY, d.id)
        except _UNCONFIRMED as exc:
            # The order may still reach the exchange and fill: stay in `_awaiting_fill` so
            # its FILLED `OrderResult` from the user stream still places SL/TP.
            log.error(
                "entry order %s for decision %s unconfirmed (%s); waiting for a stream update",
                req.client_order_id,
                d.id,
                exc,
            )
            return
        except Exception:
            self._awaiting_fill.pop(req.client_order_id, None)
            log.exception("entry order %s for decision %s failed", req.client_order_id, d.id)
            return
        if res.status == OrderStatus.FILLED:
            await self._on_entry_filled(req.client_order_id, res)
        elif res.status not in (OrderStatus.NEW, OrderStatus.PARTIALLY_FILLED):
            self._awaiting_fill.pop(req.client_order_id, None)
            log.warning("entry order %s ended %s", req.client_order_id, res.status.value)

    async def _on_entry_filled(self, client_order_id: str, res: OrderResult) -> None:
        d = self._awaiting_fill.pop(client_order_id, None)
        if d is None:  # already handled by the other path
            return
        self._entry_time[d.symbol] = _Held(entered_at=self._clock(), max_hold_s=d.max_hold_s)
        try:
            await self._place_protective(d, res.avg_price)
        except Exception:
            log.exception("placing protective orders for %s failed; flattening", d.symbol)
            await self._flatten_unprotected(d.symbol)

    async def _place_protective(self, d: Decision, avg: Decimal) -> None:
        filters = self._broker.exchange_info.filters_for(d.symbol)
        one = Decimal(1)
        if d.side == Side.BUY:
            sl_price = filters.round_price(avg * (one - d.stop_loss_pct))
            tp_price = filters.round_price(avg * (one + d.take_profit_pct))
        else:
            sl_price = filters.round_price(avg * (one + d.stop_loss_pct))
            tp_price = filters.round_price(avg * (one - d.take_profit_pct))
        exit_side = _opposite(d.side)
        for typ, role, price in (
            (OrderType.STOP_MARKET, OrderRole.STOP_LOSS, sl_price),
            (OrderType.TAKE_PROFIT_MARKET, OrderRole.TAKE_PROFIT, tp_price),
        ):
            req = OrderRequest(
                symbol=d.symbol,
                side=exit_side,
                type=typ,
                stop_price=price,
                close_position=True,
                client_order_id=new_client_order_id(),
            )
            await self._submit_recorded(req, role, d.id)

    async def _submit_recorded(
        self, req: OrderRequest, role: OrderRole, decision_id: str | None
    ) -> OrderResult:
        """Persist the order as NEW *before* submitting, so a user-stream update that races
        the REST response always finds its record; then apply the response's status unless
        an update already moved the order on (the response must not regress it to NEW)."""
        await self._store.upsert_order(self._record(req, role, decision_id, None))
        try:
            res = await self._broker.submit(req)
        except FilterViolation:
            rejected = self._record(req, role, decision_id, None)
            await self._store.upsert_order(rejected.model_copy(update={"status": OrderStatus.REJECTED}))
            raise
        current = await self._store.get_order(req.client_order_id)
        if current is None or current.status == OrderStatus.NEW or res.status != OrderStatus.NEW:
            await self._store.update_order_status(
                req.client_order_id, res.status, res.executed_qty, res.avg_price, res.order_id
            )
        return res

    async def _flatten_unprotected(self, symbol: str) -> None:
        await self._cancel_and_close(symbol, None)

    async def _close(self, d: Decision) -> None:
        await self._cancel_and_close(d.symbol, d.id)

    async def _cancel_and_close(self, symbol: str, decision_id: str | None) -> None:
        """Best-effort `cancel_all`, then always attempt `close_position`. Tracking in
        `_entry_time` is dropped only once the close succeeded (or the account is flat);
        on failure the symbol is marked overdue so the next `enforce_max_hold` pass
        (within 60 s) publishes a fresh CLOSE decision and retries."""
        try:
            await self._broker.cancel_all(symbol)
            await self._mark_protective_canceled(symbol)
        except Exception:
            log.exception("cancel_all for %s failed; closing anyway", symbol)
        try:
            res = await self._broker.close_position(symbol)
        except Exception:
            log.exception("close_position for %s failed; will retry", symbol)
            held = self._entry_time.get(symbol)
            self._entry_time[symbol] = _Held(
                entered_at=held.entered_at if held is not None else self._clock(), max_hold_s=0
            )
            return
        if res is not None:
            await self._store_close(symbol, res, decision_id)
        self._entry_time.pop(symbol, None)

    async def _store_close(self, symbol: str, res: OrderResult, decision_id: str | None = None) -> None:
        req = OrderRequest(
            symbol=symbol,
            side=res.side,
            type=res.type,
            quantity=res.orig_qty,
            reduce_only=True,
            client_order_id=res.client_order_id,
        )
        await self._store.upsert_order(self._record(req, OrderRole.CLOSE, decision_id, res))

    async def _mark_protective_canceled(self, symbol: str, *, exclude: str | None = None) -> None:
        for rec in await self._store.open_protective_orders(symbol):
            if rec.client_order_id == exclude:
                continue
            await self._store.upsert_order(
                rec.model_copy(update={"status": OrderStatus.CANCELED, "updated_at": self._now()})
            )

    # ---- fills / order updates -------------------------------------------

    async def on_fill(self, fill: Fill) -> None:
        await self._store.insert_fill(fill)
        await self._maybe_cancel_sibling(fill.client_order_id, fill.symbol)

    async def on_order_result(self, res: OrderResult) -> None:
        await self._store.update_order_status(
            res.client_order_id, res.status, res.executed_qty, res.avg_price, res.order_id
        )
        if res.status != OrderStatus.FILLED:
            return
        if res.client_order_id in self._awaiting_fill:
            await self._on_entry_filled(res.client_order_id, res)
            return
        await self._maybe_cancel_sibling(res.client_order_id, res.symbol)

    async def _maybe_cancel_sibling(self, client_order_id: str, symbol: str) -> None:
        if client_order_id in self._sibling_handled:
            return
        rec = await self._store.get_order(client_order_id)
        if rec is None or rec.role not in _PROTECTIVE_ROLES:
            return
        if client_order_id in self._sibling_handled:  # the other path got here during the await
            return
        self._sibling_handled.add(client_order_id)
        for sibling in await self._store.open_protective_orders(symbol):
            if sibling.client_order_id == client_order_id:
                continue
            try:
                await self._broker.cancel(symbol, sibling.client_order_id)
            except (PaperBrokerError, BinanceAPIError) as exc:
                if isinstance(exc, BinanceAPIError) and exc.code != _UNKNOWN_ORDER:
                    log.exception(
                        "canceling sibling %s of %s failed", sibling.client_order_id, client_order_id
                    )
                    continue
                log.warning(
                    "sibling %s of %s is already gone: %s", sibling.client_order_id, client_order_id, exc
                )
            except Exception:
                log.exception("canceling sibling %s of %s failed", sibling.client_order_id, client_order_id)
                continue
            await self._store.upsert_order(
                sibling.model_copy(update={"status": OrderStatus.CANCELED, "updated_at": self._now()})
            )
        self._entry_time.pop(symbol, None)

    # ---- max hold ---------------------------------------------------------

    async def enforce_max_hold(self) -> None:
        if await self._store.get_kv("kill_switch") == "1":
            return  # KillSwitch flattens; a CLOSE decision would only be rejected
        now = self._clock()
        positions = await self._broker.positions()
        for symbol, held in list(self._entry_time.items()):
            pos = positions.get(symbol)
            if pos is None or pos.quantity <= 0:
                self._entry_time.pop(symbol, None)
                continue
            if now - held.entered_at < held.max_hold_s:
                continue
            d = Decision(
                id=new_id(),
                symbol=symbol,
                side=Side.SELL if pos.side == PositionSide.LONG else Side.BUY,
                intent=Intent.CLOSE,
                notional_usdt=pos.notional,
                score=0.0,
                signal_ids=[],
                created_at=datetime.fromtimestamp(now, UTC),
                stop_loss_pct=self._settings.strategy.stop_loss_pct,
                take_profit_pct=self._settings.strategy.take_profit_pct,
                max_hold_s=held.max_hold_s,
            )
            await self._store.insert_decision(d)
            log.info(
                "max hold %ss reached for %s; publishing CLOSE decision %s", held.max_hold_s, symbol, d.id
            )
            self._bus.publish(d)

    # ---- helpers ----------------------------------------------------------

    def _now(self) -> datetime:
        return datetime.fromtimestamp(self._clock(), UTC)

    def _record(
        self, req: OrderRequest, role: OrderRole, decision_id: str | None, res: OrderResult | None
    ) -> OrderRecord:
        now = self._now()
        return OrderRecord(
            client_order_id=req.client_order_id,
            decision_id=decision_id,
            symbol=req.symbol,
            side=req.side,
            type=req.type,
            role=role,
            qty=req.quantity,
            price=req.price,
            stop_price=req.stop_price,
            reduce_only=req.reduce_only,
            close_position=req.close_position,
            status=res.status if res is not None else OrderStatus.NEW,
            order_id=res.order_id if res is not None else None,
            avg_price=res.avg_price if res is not None else Decimal(0),
            executed_qty=res.executed_qty if res is not None else Decimal(0),
            created_at=now,
            updated_at=now,
        )
