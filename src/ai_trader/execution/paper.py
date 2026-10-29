"""`PaperBroker`: an in-process simulated futures broker (design 5.9).

MARKET orders fill immediately at the current mark price ± `slippage_bps`, rounded down
to the symbol's tick, and are charged `qty × price × fee_rate`. STOP_MARKET /
TAKE_PROFIT_MARKET orders rest as pending and trigger off `MarkPrice` events:

* STOP_MARKET SELL at mark ≤ stop, STOP_MARKET BUY at mark ≥ stop;
* TAKE_PROFIT_MARKET SELL at mark ≥ stop, TAKE_PROFIT_MARKET BUY at mark ≤ stop.

A triggered order fills at that mark (± slippage); `close_position=True` fills the whole
position. Triggers publish both a `Fill` and an `OrderResult(status=FILLED)`; MARKET
submits publish the `Fill` and return the `OrderResult`.

Positions are one-way (one signed quantity per symbol). `Fill.realized_pnl` follows
Binance semantics: gross of commission. The wallet balance is credited the realized pnl
and debited every commission, so `account().total_wallet_balance` is net of fees.

Persistence (optional `store`): the whole simulated account — wallet balance, realized
pnl, positions, resting protective orders and the order-id counter — is written as JSON
to kv `paper_state` after every change (fill, pending add/remove, cancel), Decimals as
strings, and restored on `start()`, so a restarted process carries on with the same
account. On start the orders table is also reconciled: protective rows still open in the
DB whose client_order_id is not among the restored resting orders are marked CANCELED.
A failed state write is logged and does not fail the order operation; the next change
writes the full state again.
"""

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from ai_trader.bus import EventBus
from ai_trader.data.market_state import MarketState
from ai_trader.exchange.binance.filters import ExchangeInfo
from ai_trader.models import (
    AccountState,
    Fill,
    MarkPrice,
    OrderRequest,
    OrderResult,
    OrderStatus,
    OrderType,
    Position,
    PositionSide,
    Side,
    new_client_order_id,
)
from ai_trader.storage.db import Store

log = logging.getLogger(__name__)

_TRIGGER_TYPES = {OrderType.STOP_MARKET, OrderType.TAKE_PROFIT_MARKET}
_BPS = Decimal(10000)
PAPER_STATE_KV_KEY = "paper_state"
PAPER_STATE_BAD_KV_KEY = "paper_state_bad"
_STATE_VERSION = 1


class PaperBrokerError(RuntimeError):
    """The simulated broker cannot execute the request (e.g. no mark price yet)."""


@dataclass
class _Pos:
    qty: Decimal  # signed: > 0 long, < 0 short
    entry_price: Decimal


def _triggered(req: OrderRequest, mark: Decimal) -> bool:
    stop = req.stop_price
    if stop is None:
        return False
    if req.type == OrderType.STOP_MARKET:
        return mark <= stop if req.side == Side.SELL else mark >= stop
    if req.type == OrderType.TAKE_PROFIT_MARKET:
        return mark >= stop if req.side == Side.SELL else mark <= stop
    return False


def _parse_state(
    raw: str,
) -> tuple[Decimal, Decimal, int, dict[str, "_Pos"], dict[str, tuple[OrderRequest, int]]]:
    """Parse a `paper_state` blob completely, or raise; nothing is assigned on failure."""
    snap = json.loads(raw)
    if not isinstance(snap, dict) or snap.get("version") != _STATE_VERSION:
        raise ValueError("paper_state is not a version-1 object")
    wallet = Decimal(snap["wallet_balance"])
    realized = Decimal(snap["realized_pnl"])
    next_id = int(snap["next_order_id"])
    positions = {
        str(s): _Pos(qty=Decimal(p["qty"]), entry_price=Decimal(p["entry_price"]))
        for s, p in snap["positions"].items()
    }
    pending: dict[str, tuple[OrderRequest, int]] = {}
    for item in snap["pending"]:
        req = OrderRequest.model_validate(item["request"])
        pending[req.client_order_id] = (req, int(item["order_id"]))
    if not (wallet.is_finite() and realized.is_finite() and next_id >= 1):
        raise ValueError("paper_state holds non-finite balances or an invalid order id")
    return wallet, realized, next_id, positions, pending


class PaperBroker:
    def __init__(
        self,
        state: MarketState,
        bus: EventBus,
        exchange_info: ExchangeInfo,
        *,
        initial_balance: Decimal = Decimal(10000),
        fee_rate: Decimal = Decimal("0.0004"),
        slippage_bps: int = 2,
        clock: Callable[[], float] = time.time,
        store: Store | None = None,
    ) -> None:
        self._state = state
        self._store = store
        self._restored = False
        self._bus = bus
        self.exchange_info = exchange_info
        self._fee_rate = fee_rate
        self._slippage = Decimal(slippage_bps) / _BPS
        self._clock = clock
        self.wallet_balance = initial_balance
        self.realized_pnl = Decimal(0)  # net of commissions
        self._positions: dict[str, _Pos] = {}
        # client_order_id -> (resting trigger order, its order id)
        self._pending: dict[str, tuple[OrderRequest, int]] = {}
        self._event_marks: dict[str, Decimal] = {}
        self._next_order_id = 1
        self._subscribed = False
        self.submitted: list[OrderRequest] = []
        self.cancel_calls: list[str] = []
        self.cancel_all_calls: list[str] = []
        self.close_position_calls: list[str] = []

    # ---- lifecycle --------------------------------------------------------

    async def start(self) -> None:
        if self._store is not None and not self._restored:
            self._restored = True
            await self._restore()
        if not self._subscribed:
            self._bus.subscribe(MarkPrice, self._on_mark)
            self._subscribed = True

    async def stop(self) -> None:
        return None

    # ---- queries ----------------------------------------------------------

    def _mark(self, symbol: str) -> Decimal | None:
        mp = self._state.mark(symbol)
        if mp is not None:
            return mp.mark_price
        return self._event_marks.get(symbol)

    def can_close(self, symbol: str) -> bool:
        """Whether `close_position(symbol)` can fill now (it needs a mark price)."""
        return self._mark(symbol) is not None

    def _position(self, symbol: str, p: _Pos) -> Position:
        side = PositionSide.LONG if p.qty > 0 else PositionSide.SHORT
        qty = abs(p.qty)
        mark = self._mark(symbol) or p.entry_price
        unrealized = (mark - p.entry_price) * p.qty
        return Position(
            symbol=symbol,
            side=side,
            quantity=qty,
            entry_price=p.entry_price,
            mark_price=mark,
            unrealized_pnl=unrealized,
            leverage=1,
            liquidation_price=None,
        )

    def positions_snapshot(self) -> dict[str, Position]:
        return {s: self._position(s, p) for s, p in self._positions.items() if p.qty != 0}

    async def positions(self) -> dict[str, Position]:
        return self.positions_snapshot()

    async def account(self) -> AccountState:
        positions = list((await self.positions()).values())
        unrealized = sum((p.unrealized_pnl for p in positions), Decimal(0))
        return AccountState(
            total_wallet_balance=self.wallet_balance,
            available_balance=self.wallet_balance + unrealized,
            total_unrealized_pnl=unrealized,
            positions=positions,
            updated_at=self._now(),
        )

    async def open_order_symbols(self) -> set[str]:
        return {req.symbol for req, _ in self._pending.values()}

    async def ensure_symbol_setup(self, symbol: str, leverage: int, margin_type: str) -> None:
        return None

    # ---- orders -----------------------------------------------------------

    async def submit(self, req: OrderRequest) -> OrderResult:
        self.submitted.append(req)
        self.exchange_info.filters_for(req.symbol).validate(req)
        order_id = self._new_order_id()
        if req.type in _TRIGGER_TYPES:
            self._pending[req.client_order_id] = (req, order_id)
            await self._persist()
            return self._result(req, order_id, OrderStatus.NEW)
        if req.type != OrderType.MARKET:
            raise PaperBrokerError(f"PaperBroker does not support {req.type.value} orders")
        mark = self._mark(req.symbol)
        if mark is None:
            raise PaperBrokerError(f"no mark price for {req.symbol}")
        qty = self._fill_qty(req)
        if qty is None:
            await self._persist()  # the order id was consumed
            return self._result(req, order_id, OrderStatus.REJECTED)
        price = self._fill_price(req.symbol, req.side, mark)
        self._execute(req, order_id, qty, price)
        await self._persist()
        return self._result(req, order_id, OrderStatus.FILLED, executed_qty=qty, avg_price=price)

    async def cancel(self, symbol: str, client_order_id: str) -> OrderResult:
        self.cancel_calls.append(client_order_id)
        entry = self._pending.get(client_order_id)
        if entry is None or entry[0].symbol != symbol:
            raise PaperBrokerError(f"unknown open order {client_order_id} for {symbol}")
        del self._pending[client_order_id]
        await self._persist()
        req, order_id = entry
        return self._result(req, order_id, OrderStatus.CANCELED)

    async def cancel_all(self, symbol: str) -> None:
        self.cancel_all_calls.append(symbol)
        cids = [c for c, (r, _) in self._pending.items() if r.symbol == symbol]
        for cid in cids:
            del self._pending[cid]
        if cids:
            await self._persist()

    async def close_position(self, symbol: str) -> OrderResult | None:
        self.close_position_calls.append(symbol)
        p = self._positions.get(symbol)
        if p is None or p.qty == 0:
            return None
        req = OrderRequest(
            symbol=symbol,
            side=Side.SELL if p.qty > 0 else Side.BUY,
            type=OrderType.MARKET,
            quantity=abs(p.qty),
            reduce_only=True,
            client_order_id=new_client_order_id(),
        )
        return await self.submit(req)

    # ---- mark-driven triggers -------------------------------------------

    async def _on_mark(self, mp: MarkPrice) -> None:
        self._event_marks[mp.symbol] = mp.mark_price
        changed = False
        for cid, (req, order_id) in list(self._pending.items()):
            if req.symbol != mp.symbol or not _triggered(req, mp.mark_price):
                continue
            if self._pending.pop(cid, None) is None:  # canceled meanwhile
                continue
            changed = True
            qty = self._fill_qty(req)
            if qty is None:
                log.info("paper %s %s triggered with no position to reduce; expired", req.type.value, cid)
                self._bus.publish(self._result(req, order_id, OrderStatus.EXPIRED))
                continue
            price = self._fill_price(req.symbol, req.side, mp.mark_price)
            self._execute(req, order_id, qty, price)
            self._bus.publish(
                self._result(req, order_id, OrderStatus.FILLED, executed_qty=qty, avg_price=price)
            )
        if changed:
            await self._persist()

    # ---- persistence ------------------------------------------------------

    def _snapshot(self) -> dict:
        return {
            "version": _STATE_VERSION,
            "wallet_balance": str(self.wallet_balance),
            "realized_pnl": str(self.realized_pnl),
            "next_order_id": self._next_order_id,
            "positions": {
                s: {"qty": str(p.qty), "entry_price": str(p.entry_price)}
                for s, p in self._positions.items()
                if p.qty != 0
            },
            "pending": [
                {"order_id": oid, "request": req.model_dump(mode="json")}
                for req, oid in self._pending.values()
            ],
        }

    async def _persist(self) -> None:
        if self._store is None:
            return
        payload = json.dumps(self._snapshot())  # taken now, before any await
        try:
            await self._store.set_kv(PAPER_STATE_KV_KEY, payload)
        except Exception:
            log.exception("paper broker: persisting state failed; the next change writes it again")

    async def _restore(self) -> None:
        assert self._store is not None
        raw = await self._store.get_kv(PAPER_STATE_KV_KEY)
        if raw is not None:
            try:
                wallet, realized, next_id, positions, pending = _parse_state(raw)
            except Exception:
                # Never crash-loop on a bad blob: keep it for inspection, start from scratch.
                log.exception(
                    "paper broker: unreadable %s; saved as %s, starting from initial balance %s",
                    PAPER_STATE_KV_KEY,
                    PAPER_STATE_BAD_KV_KEY,
                    self.wallet_balance,
                )
                await self._store.set_kv(PAPER_STATE_BAD_KV_KEY, raw)
            else:
                self.wallet_balance, self.realized_pnl = wallet, realized
                self._next_order_id = max(self._next_order_id, next_id)
                self._positions, self._pending = positions, pending
                log.info(
                    "paper broker: restored state (wallet=%s positions=%s resting_orders=%d)",
                    self.wallet_balance,
                    ",".join(f"{s}:{p.qty}" for s, p in self._positions.items()) or "none",
                    len(self._pending),
                )
        try:
            await self._reconcile_orders()
        except Exception:
            log.exception("paper broker: reconciling the orders table failed")

    async def _reconcile_orders(self) -> None:
        """Mark protective rows the DB still shows as open, but which no longer rest here, CANCELED."""
        assert self._store is not None
        for symbol in await self._store.symbols_with_open_protective_orders():
            for rec in await self._store.open_protective_orders(symbol):
                if rec.client_order_id in self._pending:
                    continue
                await self._store.update_order_status(
                    rec.client_order_id,
                    OrderStatus.CANCELED,
                    rec.executed_qty,
                    rec.avg_price,
                    rec.order_id if rec.order_id is not None else 0,
                )
                log.info(
                    "paper broker: stale protective order %s (%s) marked CANCELED", rec.client_order_id, symbol
                )

    # ---- internals --------------------------------------------------------

    def _now(self) -> datetime:
        return datetime.fromtimestamp(self._clock(), UTC)

    def _new_order_id(self) -> int:
        oid = self._next_order_id
        self._next_order_id += 1
        return oid

    def _fill_price(self, symbol: str, side: Side, mark: Decimal) -> Decimal:
        factor = 1 + self._slippage if side == Side.BUY else 1 - self._slippage
        return self.exchange_info.filters_for(symbol).round_price(mark * factor)

    def _fill_qty(self, req: OrderRequest) -> Decimal | None:
        """Quantity actually executed, or None if a reducing order has nothing to reduce."""
        p = self._positions.get(req.symbol)
        current = p.qty if p is not None else Decimal(0)
        reduces = (current > 0 and req.side == Side.SELL) or (current < 0 and req.side == Side.BUY)
        if req.close_position:
            return abs(current) if reduces else None
        qty = req.quantity
        if qty is None or qty <= 0:
            return None
        if req.reduce_only:
            return min(qty, abs(current)) if reduces else None
        return qty

    def _execute(self, req: OrderRequest, order_id: int, qty: Decimal, price: Decimal) -> None:
        realized = self._apply(req.symbol, req.side, qty, price)
        commission = qty * price * self._fee_rate
        self.wallet_balance += realized - commission
        self.realized_pnl += realized - commission
        self._bus.publish(
            Fill(
                order_id=order_id,
                client_order_id=req.client_order_id,
                symbol=req.symbol,
                side=req.side,
                price=price,
                qty=qty,
                realized_pnl=realized,
                commission=commission,
                event_time=self._now(),
            )
        )

    def _apply(self, symbol: str, side: Side, qty: Decimal, price: Decimal) -> Decimal:
        """Update the one-way position and return the realized pnl (gross of fees)."""
        delta = qty if side == Side.BUY else -qty
        p = self._positions.get(symbol)
        if p is None or p.qty == 0:
            self._positions[symbol] = _Pos(qty=delta, entry_price=price)
            return Decimal(0)
        if (p.qty > 0) == (delta > 0):  # adding to the position
            new_qty = p.qty + delta
            p.entry_price = (abs(p.qty) * p.entry_price + qty * price) / abs(new_qty)
            p.qty = new_qty
            return Decimal(0)
        closing = min(qty, abs(p.qty))
        direction = 1 if p.qty > 0 else -1
        realized = (price - p.entry_price) * closing * direction
        remaining = qty - closing
        if remaining > 0:  # flipped through zero
            self._positions[symbol] = _Pos(qty=remaining if delta > 0 else -remaining, entry_price=price)
        else:
            p.qty += delta
            if p.qty == 0:
                del self._positions[symbol]
        return realized

    def _result(
        self,
        req: OrderRequest,
        order_id: int,
        status: OrderStatus,
        *,
        executed_qty: Decimal = Decimal(0),
        avg_price: Decimal = Decimal(0),
    ) -> OrderResult:
        return OrderResult(
            order_id=order_id,
            client_order_id=req.client_order_id,
            symbol=req.symbol,
            side=req.side,
            type=req.type,
            status=status,
            orig_qty=req.quantity if req.quantity is not None else executed_qty,
            executed_qty=executed_qty,
            avg_price=avg_price,
            stop_price=req.stop_price,
            reduce_only=req.reduce_only,
            close_position=req.close_position,
            update_time=self._now(),
        )
