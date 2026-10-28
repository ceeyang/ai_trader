import json
import pathlib
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from ai_trader.exchange.binance.errors import UnknownSymbol
from ai_trader.exchange.binance.parsers import (
    parse_account_update,
    parse_exchange_info,
    parse_force_order,
    parse_kline,
    parse_mark_price,
    parse_order_trade_update,
    parse_rest_account,
    parse_rest_kline,
    parse_rest_order,
    parse_rest_position,
    parse_rest_premium_index,
)
from ai_trader.models import OrderStatus, OrderType, PositionSide, Side

FX = pathlib.Path(__file__).parents[1] / "fixtures" / "binance"


def fx(name: str):
    return json.loads((FX / name).read_text())


# ---- REST ------------------------------------------------------------------


def test_parse_exchange_info_keeps_only_trading_perpetuals():
    info = parse_exchange_info(fx("exchange_info.json"))
    assert set(info.symbols) == {"BTCUSDT", "ETHUSDT"}
    btc = info.filters_for("BTCUSDT")
    assert btc.tick_size == Decimal("0.10")
    assert btc.step_size == Decimal("0.001")
    assert btc.min_qty == Decimal("0.001")
    assert btc.max_qty == Decimal(1000)
    assert btc.min_notional == Decimal(100)
    assert (btc.price_precision, btc.quantity_precision) == (2, 3)
    eth = info.filters_for("ETHUSDT")
    assert eth.tick_size == Decimal("0.01") and eth.min_notional == Decimal(20)


def test_exchange_info_unknown_symbol_raises():
    info = parse_exchange_info(fx("exchange_info.json"))
    with pytest.raises(UnknownSymbol):
        info.filters_for("XYZUSDT")


def test_parse_rest_premium_index():
    mp = parse_rest_premium_index(fx("premium_index.json"))
    assert mp.symbol == "BTCUSDT"
    assert mp.mark_price == Decimal("80876.26033380")
    assert mp.funding_rate == Decimal("0.00010000")
    assert mp.next_funding_time == datetime.fromtimestamp(1793232000, UTC)
    assert mp.event_time.tzinfo is not None


def test_parse_rest_order():
    raw = fx("order_response.json")
    o = parse_rest_order(raw)
    assert o.order_id == raw["orderId"] and o.client_order_id == raw["clientOrderId"]
    assert o.side == Side.BUY and o.type == OrderType.MARKET and o.status == OrderStatus.NEW
    assert o.orig_qty == Decimal(10) and o.executed_qty == Decimal(0)
    assert o.stop_price is None
    assert o.reduce_only is False and o.close_position is False
    assert o.update_time == datetime.fromtimestamp(1566818724.722, UTC)


def test_parse_rest_position_short_and_flat():
    btc, eth = (parse_rest_position(r) for r in fx("position_risk_v2.json"))
    assert btc.side == PositionSide.SHORT and btc.quantity == Decimal("0.002")
    assert btc.entry_price == Decimal("80950.10000") and btc.leverage == 2
    assert btc.liquidation_price == Decimal("121010.37000000")
    assert eth.side == PositionSide.FLAT and eth.quantity == Decimal(0)
    assert eth.liquidation_price is None


def test_parse_rest_position_long():
    raw = dict(fx("position_risk_v2.json")[0], positionAmt="0.005")
    p = parse_rest_position(raw)
    assert p.side == PositionSide.LONG and p.quantity == Decimal("0.005")


def test_parse_rest_account():
    acc = parse_rest_account(fx("account_v2.json"))
    assert acc.total_wallet_balance == Decimal("15000.00000000")
    assert acc.available_balance == Decimal("14919.27685933")
    assert acc.total_unrealized_pnl == Decimal("0.14767933")
    assert [p.symbol for p in acc.open_positions()] == ["BTCUSDT"]
    btc = acc.open_positions()[0]
    assert btc.side == PositionSide.SHORT and btc.quantity == Decimal("0.002")


def test_parse_rest_kline():
    row = [1700000000000, "80000.0", "80100.0", "79900.0", "80050.0", "12.345",
           1700000059999, "988000.0", 100, "6.0", "480000.0", "0"]
    k = parse_rest_kline(row, symbol="BTCUSDT", interval="1m")
    assert k.symbol == "BTCUSDT" and k.interval == "1m"
    assert k.open_time == datetime.fromtimestamp(1700000000, UTC)
    assert (k.open, k.high, k.low, k.close, k.volume) == (
        Decimal("80000.0"), Decimal("80100.0"), Decimal("79900.0"), Decimal("80050.0"), Decimal("12.345"))
    assert k.is_closed is True


# ---- WS ----------------------------------------------------------------


def test_parse_mark_price_fixture():
    mp = parse_mark_price(fx("ws_mark_price.json"))
    assert mp.symbol == "BTCUSDT" and mp.mark_price == Decimal("80874.42344203") and mp.funding_rate == Decimal("0.00010000")
    assert mp.next_funding_time.tzinfo is not None and int(mp.next_funding_time.timestamp()) == 1793232000


def test_parse_kline_fixture():
    k = parse_kline(fx("ws_kline.json"))
    assert k.symbol == "BTCUSDT" and k.interval == "1m" and k.is_closed is False
    assert k.open == Decimal("80900.10") and k.close == Decimal("80905.00")
    assert k.open_time.tzinfo is not None and int(k.close_time.timestamp()) == 1793212439


def test_parse_force_order_sell_means_long_liquidated():
    liq = parse_force_order(fx("ws_force_order.json"))
    assert liq.side == Side.SELL and liq.notional == Decimal("9910") * Decimal("0.014")  # noqa: FURB157


def test_parse_order_trade_update_produces_fill():
    res, fill = parse_order_trade_update(fx("ws_order_trade_update_fill.json"))
    assert res.status == OrderStatus.FILLED and res.client_order_id == "ait-abc" and res.order_id == 8886774
    assert fill is not None and fill.qty == Decimal("0.002") and fill.price == Decimal("80000") and fill.realized_pnl == Decimal("1.5")  # noqa: FURB157


def test_parse_order_trade_update_new_has_no_fill():
    d = fx("ws_order_trade_update_fill.json"); d["o"]["x"] = "NEW"; d["o"]["X"] = "NEW"; d["o"]["l"] = "0"
    _, fill = parse_order_trade_update(d); assert fill is None


def test_parse_account_update_positions_and_balance():
    upd = parse_account_update(fx("ws_account_update.json"))
    assert upd.state.total_wallet_balance == Decimal("10001.2") and upd.state.positions[0].side == PositionSide.LONG
