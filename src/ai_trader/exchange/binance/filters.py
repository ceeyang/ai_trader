"""Per-symbol exchange filters: rounding and order validation (design 5.4)."""

from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from ai_trader.exchange.binance.errors import FilterViolation, UnknownSymbol
from ai_trader.models import OrderRequest


def _floor_to(value: Decimal, step: Decimal) -> Decimal:
    """Round `value` down to a multiple of `step`, expressed with `step`'s exponent."""
    units = (value / step).to_integral_value(rounding=ROUND_FLOOR)
    return (units * step).quantize(step)


def _aligned(value: Decimal, step: Decimal) -> bool:
    return value % step == 0


@dataclass(frozen=True)
class SymbolFilters:
    symbol: str
    tick_size: Decimal
    step_size: Decimal
    min_qty: Decimal
    max_qty: Decimal
    min_notional: Decimal
    price_precision: int
    quantity_precision: int

    def round_price(self, price: Decimal) -> Decimal:
        """Round down to the tick size."""
        return _floor_to(price, self.tick_size)

    def round_qty(self, qty: Decimal) -> Decimal:
        """Round down to the step size."""
        return _floor_to(qty, self.step_size)

    def qty_for_notional(self, notional: Decimal, price: Decimal) -> Decimal:
        """Largest step-aligned quantity whose notional at `price` does not exceed `notional`."""
        if price <= 0:
            raise FilterViolation(f"{self.symbol}: price must be positive, got {price}")
        qty = self.round_qty(notional / price)
        if qty < self.min_qty:
            raise FilterViolation(f"{self.symbol}: qty {qty} below min_qty {self.min_qty}")
        if qty > self.max_qty:
            raise FilterViolation(f"{self.symbol}: qty {qty} above max_qty {self.max_qty}")
        if qty * price < self.min_notional:
            raise FilterViolation(
                f"{self.symbol}: notional {qty * price} below min_notional {self.min_notional}"
            )
        return qty

    def min_qty_for_price(self, price: Decimal) -> Decimal:
        """Smallest step-aligned quantity (≥ `min_qty`) whose notional at `price` is at
        least `min_notional`: the exchange's minimum order size at this price."""
        if price <= 0:
            raise FilterViolation(f"{self.symbol}: price must be positive, got {price}")
        units = (self.min_notional / price / self.step_size).to_integral_value(rounding=ROUND_CEILING)
        qty = (units * self.step_size).quantize(self.step_size)
        return max(qty, self.min_qty)

    def validate(self, req: OrderRequest) -> None:
        """Raise FilterViolation if quantity / prices are unaligned or below the minimums."""
        if req.quantity is None:
            if not req.close_position:
                raise FilterViolation(f"{self.symbol}: quantity required unless close_position")
        else:
            qty = req.quantity
            if not _aligned(qty, self.step_size):
                raise FilterViolation(f"{self.symbol}: qty {qty} not aligned to step {self.step_size}")
            if qty < self.min_qty:
                raise FilterViolation(f"{self.symbol}: qty {qty} below min_qty {self.min_qty}")
            if qty > self.max_qty:
                raise FilterViolation(f"{self.symbol}: qty {qty} above max_qty {self.max_qty}")
        for name, px in (("price", req.price), ("stop_price", req.stop_price)):
            if px is None:
                continue
            if px <= 0:
                raise FilterViolation(f"{self.symbol}: {name} must be positive, got {px}")
            if not _aligned(px, self.tick_size):
                raise FilterViolation(f"{self.symbol}: {name} {px} not aligned to tick {self.tick_size}")
        if req.quantity is not None and req.price is not None and not req.reduce_only:
            notional = req.quantity * req.price
            if notional < self.min_notional:
                raise FilterViolation(
                    f"{self.symbol}: notional {notional} below min_notional {self.min_notional}"
                )


@dataclass(frozen=True)
class ExchangeInfo:
    symbols: dict[str, SymbolFilters] = field(default_factory=dict)

    def filters_for(self, symbol: str) -> SymbolFilters:
        try:
            return self.symbols[symbol]
        except KeyError:
            raise UnknownSymbol(symbol) from None
