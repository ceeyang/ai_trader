# tests/unit/test_store.py
from datetime import timedelta
from decimal import Decimal

from conftest import T0, make_fill, make_news, make_order_record, make_signal

from ai_trader.models import OrderRole, OrderStatus
from ai_trader.storage.db import Store


async def test_insert_news_dedupes(tmp_path):
    st = Store(tmp_path / "t.db"); await st.open()
    item = make_news("n1")
    assert await st.insert_news(item) is True and await st.insert_news(item) is False and await st.news_exists("n1")
    await st.close()


async def test_signals_forward_returns_and_effectiveness(tmp_path):
    st = Store(tmp_path / "t.db"); await st.open()
    await st.insert_signal(make_signal("s1", detector="funding_extreme", created_at=T0))
    assert [x.id for x in await st.signals_missing_forward_return(600, before=T0 + timedelta(seconds=601))] == ["s1"]
    await st.insert_forward_return("s1", 600, 0.004)
    assert await st.signals_missing_forward_return(600, before=T0 + timedelta(hours=1)) == []
    rows = await st.effectiveness()
    assert rows[0].detector == "funding_extreme" and rows[0].n == 1 and rows[0].hit_rate == 1.0
    await st.close()


async def test_mark_at_uses_nearest_within_tolerance(tmp_path):
    st = Store(tmp_path / "t.db"); await st.open()
    await st.insert_mark_sample("BTCUSDT", T0, Decimal("80000"))  # noqa: FURB157
    await st.insert_mark_sample("BTCUSDT", T0 + timedelta(seconds=30), Decimal("80100"))  # noqa: FURB157
    assert await st.mark_at("BTCUSDT", T0 + timedelta(seconds=25)) == Decimal("80100")  # noqa: FURB157
    assert await st.mark_at("BTCUSDT", T0 + timedelta(hours=1)) is None
    await st.close()


async def test_realized_pnl_and_consecutive_losses(tmp_path):
    st = Store(tmp_path / "t.db"); await st.open()
    for i, pnl in enumerate(["5", "-1", "0", "-2", "-3"]):
        await st.insert_fill(make_fill(f"c{i}", realized_pnl=Decimal(pnl), event_time=T0 + timedelta(minutes=i)))
    assert await st.realized_pnl_since(T0 + timedelta(minutes=1)) == Decimal("-6")  # noqa: FURB157
    assert await st.consecutive_losses() == 3   # 0 被过滤后 -3,-2,-1 连续三笔
    await st.close()


async def test_kv_and_orders_roundtrip(tmp_path):
    st = Store(tmp_path / "t.db"); await st.open()
    await st.set_kv("kill_switch", "1"); assert await st.get_kv("kill_switch") == "1"
    await st.upsert_order(make_order_record("ait-1", role=OrderRole.STOP_LOSS, status=OrderStatus.NEW))
    assert (await st.get_order("ait-1")).role == OrderRole.STOP_LOSS
    assert [o.client_order_id for o in await st.open_protective_orders("BTCUSDT")] == ["ait-1"]
    await st.update_order_status("ait-1", OrderStatus.FILLED, Decimal("0.002"), Decimal("79000"), 99)  # noqa: FURB157
    assert await st.open_protective_orders("BTCUSDT") == []
    await st.close()
