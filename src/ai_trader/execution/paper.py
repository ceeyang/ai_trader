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
"""

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

log = logging.getLogger(__name__)

_TRIGGER_TYPES = {OrderType.STOP_MARKET, OrderType.TAKE_PROFIT_MARKET}
_BPS = Decimal(10000)


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
    ) -> None:
        self._state = state
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
            return self._result(req, order_id, OrderStatus.NEW)
        if req.type != OrderType.MARKET:
            raise PaperBrokerError(f"PaperBroker does not support {req.type.value} orders")
        mark = self._mark(req.symbol)
        if mark is None:
            raise PaperBrokerError(f"no mark price for {req.symbol}")
        qty = self._fill_qty(req)
        if qty is None:
            return self._result(req, order_id, OrderStatus.REJECTED)
        price = self._fill_price(req.symbol, req.side, mark)
        self._execute(req, order_id, qty, price)
        return self._result(req, order_id, OrderStatus.FILLED, executed_qty=qty, avg_price=price)

    async def cancel(self, symbol: str, client_order_id: str) -> OrderResult:
        self.cancel_calls.append(client_order_id)
        entry = self._pending.get(client_order_id)
        if entry is None or entry[0].symbol != symbol:
            raise PaperBrokerError(f"unknown open order {client_order_id} for {symbol}")
        del self._pending[client_order_id]
        req, order_id = entry
        return self._result(req, order_id, OrderStatus.CANCELED)

    async def cancel_all(self, symbol: str) -> None:
        self.cancel_all_calls.append(symbol)
        for cid in [c for c, (r, _) in self._pending.items() if r.symbol == symbol]:
            del self._pending[cid]

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
        for cid, (req, order_id) in list(self._pending.items()):
            if req.symbol != mp.symbol or not _triggered(req, mp.mark_price):
                continue
            if self._pending.pop(cid, None) is None:  # canceled meanwhile
                continue
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
