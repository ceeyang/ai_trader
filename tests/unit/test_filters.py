# tests/unit/test_filters.py
from decimal import Decimal  # noqa: I001
import pytest
from ai_trader.exchange.binance.errors import FilterViolation
from ai_trader.exchange.binance.filters import SymbolFilters
from ai_trader.models import OrderRequest, OrderType, Side

F = SymbolFilters("BTCUSDT", Decimal("0.10"), Decimal("0.001"), Decimal("0.001"), Decimal("1000"), Decimal("100"), 2, 3)  # noqa: FURB157

def test_round_price_floors_to_tick(): assert F.round_price(Decimal("80876.26")) == Decimal("80876.20")
def test_round_qty_floors_to_step(): assert F.round_qty(Decimal("0.0029")) == Decimal("0.002")
def test_qty_for_notional(): assert F.qty_for_notional(Decimal("200"), Decimal("80000")) == Decimal("0.002")  # noqa: FURB157
def test_qty_for_notional_below_min_notional_raises():
    with pytest.raises(FilterViolation): F.qty_for_notional(Decimal("50"), Decimal("80000"))  # noqa: FURB157
def test_qty_for_notional_below_min_qty_raises():
    with pytest.raises(FilterViolation): F.qty_for_notional(Decimal("150"), Decimal("200000"))  # noqa: FURB157
def test_validate_rejects_unaligned_qty():
    req = OrderRequest(symbol="BTCUSDT", side=Side.BUY, type=OrderType.MARKET, quantity=Decimal("0.0015"), client_order_id="ait-x")
    with pytest.raises(FilterViolation): F.validate(req)
def test_validate_allows_close_position_without_qty():
    req = OrderRequest(symbol="BTCUSDT", side=Side.SELL, type=OrderType.STOP_MARKET, stop_price=Decimal("79000.0"),
                       close_position=True, client_order_id="ait-y")
    F.validate(req)
def test_min_qty_for_price():
    assert F.min_qty_for_price(Decimal(80000)) == Decimal("0.002")  # 0.001 -> 80 < 100
    assert F.min_qty_for_price(Decimal(100000)) == Decimal("0.001")  # exactly 100
    assert F.min_qty_for_price(Decimal(1000000)) == Decimal("0.001")  # min_qty dominates
