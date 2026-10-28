import re  # noqa: I001
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest
from ai_trader.models import (Direction, Liquidation, Position, PositionSide, RiskVerdict, Side, Signal,
                              new_client_order_id)

def test_signal_signed_strength():
    now = datetime.now(timezone.utc)  # noqa: UP017
    s = Signal(id="a", detector="d", symbol="BTCUSDT", direction=Direction.BEARISH, strength=0.8,
               created_at=now, expires_at=now + timedelta(hours=1), ref_price=Decimal("80000"), rationale="x")  # noqa: FURB157
    assert s.signed_strength == -0.8

def test_client_order_id_matches_binance_pattern():
    cid = new_client_order_id()
    assert len(cid) == 32 and re.fullmatch(r"[\.A-Z\:/a-z0-9_-]{1,36}", cid) and cid.startswith("ait-")

def test_liquidation_and_position_notional():
    liq = Liquidation(symbol="BTCUSDT", side=Side.SELL, price=Decimal("80000"), qty=Decimal("0.5"),  # noqa: FURB157
                      event_time=datetime.now(timezone.utc))  # noqa: UP017
    assert liq.notional == Decimal("40000")  # noqa: FURB157
    p = Position(symbol="BTCUSDT", side=PositionSide.LONG, quantity=Decimal("0.002"), entry_price=Decimal("1"),  # noqa: FURB157
                 mark_price=Decimal("80000"), unrealized_pnl=Decimal("0"), leverage=2, liquidation_price=None)  # noqa: FURB157
    assert p.notional == Decimal("160")  # noqa: FURB157

def test_models_are_frozen():
    v = RiskVerdict(approved=True)
    with pytest.raises(Exception):  # noqa: B017
        v.approved = False  # type: ignore[misc]
