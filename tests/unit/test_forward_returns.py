from datetime import timedelta
from decimal import Decimal

from conftest import T0, make_signal

from ai_trader.analysis.forward_returns import ForwardReturnTracker
from ai_trader.data.market_state import MarketState
from ai_trader.models import Direction


async def test_forward_return_computed_from_samples(st):
    await st.insert_signal(make_signal("s1", direction=Direction.BEARISH, ref_price=Decimal("80000"), created_at=T0))  # noqa: FURB157
    await st.insert_mark_sample("BTCUSDT", T0 + timedelta(seconds=600), Decimal("79200"))  # noqa: FURB157
    tr = ForwardReturnTracker(st, MarketState(), horizons_s=(600,), clock=lambda: (T0 + timedelta(seconds=700)).timestamp())
    await tr.tick()
    rows = await st.effectiveness(); assert rows[0].n == 1 and abs(rows[0].mean_ret - 0.01) < 1e-9   # (79200-80000)/80000 × (-1)


async def test_forward_return_skips_when_no_sample(st):
    await st.insert_signal(make_signal("s1", created_at=T0))
    tr = ForwardReturnTracker(st, MarketState(), horizons_s=(600,), clock=lambda: (T0 + timedelta(seconds=700)).timestamp())
    await tr.tick(); assert await st.effectiveness() == []


async def test_forward_return_not_computed_before_horizon(st):
    await st.insert_signal(make_signal("s1", created_at=T0))
    await st.insert_mark_sample("BTCUSDT", T0 + timedelta(seconds=600), Decimal(80800))
    tr = ForwardReturnTracker(st, MarketState(), horizons_s=(600,), clock=lambda: (T0 + timedelta(seconds=500)).timestamp())
    await tr.tick()
    assert await st.effectiveness() == []


async def test_forward_return_run_stops_promptly(st):
    import asyncio

    tr = ForwardReturnTracker(st, MarketState(), horizons_s=(600,), interval_s=3600)
    task = asyncio.create_task(tr.run())
    await asyncio.sleep(0.05)
    await tr.stop()
    await asyncio.wait_for(task, 1)
