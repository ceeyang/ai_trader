"""Pure functions turning raw Binance payloads into domain models (design 5.4)."""

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from ai_trader.exchange.binance.filters import ExchangeInfo, SymbolFilters
from ai_trader.models import (
    AccountState,
    AccountUpdate,
    Fill,
    Kline,
    Liquidation,
    MarkPrice,
    OrderResult,
    OrderStatus,
    OrderType,
    Position,
    PositionSide,
    Side,
    utc_now,
)

log = logging.getLogger(__name__)


def _ms(ms: int | str) -> datetime:
    return datetime.fromtimestamp(int(ms) / 1000, UTC)


def _dec(value: Any) -> Decimal:
    return Decimal(str(value))


def _dec_or_none(value: Any) -> Decimal | None:
    """Decimal, or None when the field is missing or zero (Binance's "unset")."""
    if value is None or value == "":
        return None
    d = _dec(value)
    return None if d == 0 else d


def _bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.lower() == "true"
    return bool(value)


# ---- REST -------------------------------------------------------------------


def parse_exchange_info(raw: dict) -> ExchangeInfo:
    """Keep only PERPETUAL contracts in TRADING status. A symbol missing PRICE_FILTER or
    LOT_SIZE is skipped (logged) rather than failing the whole load; a missing
    MIN_NOTIONAL is treated as 0 (logged)."""
    symbols: dict[str, SymbolFilters] = {}
    for s in raw.get("symbols", []):
        if s.get("contractType") != "PERPETUAL" or s.get("status") != "TRADING":
            continue
        by_type = {f["filterType"]: f for f in s.get("filters", [])}
        price_f = by_type.get("PRICE_FILTER")
        lot_f = by_type.get("LOT_SIZE")
        if price_f is None or lot_f is None:
            missing = [n for n, f in (("PRICE_FILTER", price_f), ("LOT_SIZE", lot_f)) if f is None]
            log.warning("exchange info: skipping %s, missing %s", s.get("symbol"), ",".join(missing))
            continue
        notional_f = by_type.get("MIN_NOTIONAL")
        if notional_f is None:
            log.warning("exchange info: %s has no MIN_NOTIONAL filter; treating it as 0", s.get("symbol"))
            notional_f = {}
        symbols[s["symbol"]] = SymbolFilters(
            symbol=s["symbol"],
            tick_size=_dec(price_f["tickSize"]),
            step_size=_dec(lot_f["stepSize"]),
            min_qty=_dec(lot_f["minQty"]),
            max_qty=_dec(lot_f["maxQty"]),
            min_notional=_dec(notional_f.get("notional", "0")),
            price_precision=int(s["pricePrecision"]),
            quantity_precision=int(s["quantityPrecision"]),
        )
    return ExchangeInfo(symbols=symbols)


def parse_rest_premium_index(raw: dict) -> MarkPrice:
    """GET /fapi/v1/premiumIndex (single symbol)."""
    return MarkPrice(
        symbol=raw["symbol"],
        mark_price=_dec(raw["markPrice"]),
        index_price=_dec(raw["indexPrice"]),
        funding_rate=_dec(raw["lastFundingRate"]),
        next_funding_time=_ms(raw["nextFundingTime"]),
        event_time=_ms(raw["time"]),
    )


def parse_rest_kline(row: list, *, symbol: str, interval: str) -> Kline:
    """One row of GET /fapi/v1/klines: [openTime, o, h, l, c, v, closeTime, ...]."""
    close_time = _ms(row[6])
    return Kline(
        symbol=symbol,
        interval=interval,
        open_time=_ms(row[0]),
        close_time=close_time,
        open=_dec(row[1]),
        high=_dec(row[2]),
        low=_dec(row[3]),
        close=_dec(row[4]),
        volume=_dec(row[5]),
        is_closed=close_time < utc_now(),
    )


def parse_rest_order(raw: dict) -> OrderResult:
    """Order payload from POST/GET/DELETE /fapi/v1/order and GET /fapi/v1/openOrders."""
    return OrderResult(
        order_id=int(raw["orderId"]),
        client_order_id=raw["clientOrderId"],
        symbol=raw["symbol"],
        side=Side(raw["side"]),
        type=OrderType(raw.get("origType") or raw["type"]),
        status=OrderStatus(raw["status"]),
        orig_qty=_dec(raw["origQty"]),
        executed_qty=_dec(raw["executedQty"]),
        avg_price=_dec(raw.get("avgPrice", "0")),
        stop_price=_dec_or_none(raw.get("stopPrice")),
        reduce_only=_bool(raw.get("reduceOnly", False)),
        close_position=_bool(raw.get("closePosition", False)),
        update_time=_ms(raw["updateTime"]),
    )


def _side_and_qty(position_amt: Any) -> tuple[PositionSide, Decimal]:
    amt = _dec(position_amt)
    if amt > 0:
        return PositionSide.LONG, amt
    if amt < 0:
        return PositionSide.SHORT, -amt
    return PositionSide.FLAT, Decimal(0)


def parse_rest_position(raw: dict) -> Position:
    """One entry of GET /fapi/v2/positionRisk (one-way mode)."""
    side, qty = _side_and_qty(raw["positionAmt"])
    return Position(
        symbol=raw["symbol"],
        side=side,
        quantity=qty,
        entry_price=_dec(raw["entryPrice"]),
        mark_price=_dec(raw["markPrice"]),
        unrealized_pnl=_dec(raw["unRealizedProfit"]),
        leverage=int(raw["leverage"]),
        liquidation_price=_dec_or_none(raw.get("liquidationPrice")),
    )


def _parse_account_position(raw: dict) -> Position:
    # /fapi/v2/account positions carry no markPrice / liquidationPrice:
    # mark price is derived from |notional| / |positionAmt|.
    side, qty = _side_and_qty(raw["positionAmt"])
    mark = abs(_dec(raw.get("notional", "0"))) / qty if qty else Decimal(0)
    return Position(
        symbol=raw["symbol"],
        side=side,
        quantity=qty,
        entry_price=_dec(raw["entryPrice"]),
        mark_price=mark,
        unrealized_pnl=_dec(raw["unrealizedProfit"]),
        leverage=int(raw["leverage"]),
        liquidation_price=None,
    )


def parse_rest_account(raw: dict) -> AccountState:
    """GET /fapi/v2/account. Only non-zero positions are kept."""
    positions = [
        _parse_account_position(p) for p in raw.get("positions", []) if _dec(p["positionAmt"]) != 0
    ]
    return AccountState(
        total_wallet_balance=_dec(raw["totalWalletBalance"]),
        available_balance=_dec(raw["availableBalance"]),
        total_unrealized_pnl=_dec(raw["totalUnrealizedProfit"]),
        positions=positions,
        updated_at=utc_now(),
    )


# ---- WebSocket streams -------------------------------------------------------


def parse_mark_price(d: dict) -> MarkPrice:
    """markPriceUpdate stream payload."""
    return MarkPrice(
        symbol=d["s"],
        mark_price=_dec(d["p"]),
        index_price=_dec(d["i"]),
        funding_rate=_dec(d["r"]),
        next_funding_time=_ms(d["T"]),
        event_time=_ms(d["E"]),
    )


def parse_kline(d: dict) -> Kline:
    """kline stream payload (the nested `k` object)."""
    k = d["k"]
    return Kline(
        symbol=k["s"],
        interval=k["i"],
        open_time=_ms(k["t"]),
        close_time=_ms(k["T"]),
        open=_dec(k["o"]),
        high=_dec(k["h"]),
        low=_dec(k["l"]),
        close=_dec(k["c"]),
        volume=_dec(k["v"]),
        is_closed=_bool(k["x"]),
    )


def parse_force_order(d: dict) -> Liquidation:
    """forceOrder stream payload (the nested `o` object)."""
    o = d["o"]
    return Liquidation(
        symbol=o["s"],
        side=Side(o["S"]),
        price=_dec(o["p"]),
        qty=_dec(o["q"]),
        event_time=_ms(o["T"]),
    )


def parse_order_trade_update(d: dict) -> tuple[OrderResult, Fill | None]:
    """ORDER_TRADE_UPDATE user-data payload. A Fill is only produced when the
    execution type is TRADE and a non-zero quantity was just filled."""
    o = d["o"]
    side = Side(o["S"])
    result = OrderResult(
        order_id=int(o["i"]),
        client_order_id=o["c"],
        symbol=o["s"],
        side=side,
        type=OrderType(o.get("ot") or o["o"]),
        status=OrderStatus(o["X"]),
        orig_qty=_dec(o["q"]),
        executed_qty=_dec(o["z"]),
        avg_price=_dec(o.get("ap", "0")),
        stop_price=_dec_or_none(o.get("sp")),
        reduce_only=_bool(o.get("R", False)),
        close_position=_bool(o.get("cp", False)),
        update_time=_ms(d["T"]),
    )
    last_qty = _dec(o.get("l", "0"))
    fill = None
    if o.get("x") == "TRADE" and last_qty > 0:
        fill = Fill(
            order_id=result.order_id,
            client_order_id=result.client_order_id,
            symbol=result.symbol,
            side=side,
            price=_dec(o["L"]),
            qty=last_qty,
            realized_pnl=_dec(o.get("rp", "0")),
            commission=_dec(o.get("n", "0")),
            event_time=_ms(d["T"]),
        )
    return result, fill


def parse_account_update(d: dict) -> AccountUpdate:
    """ACCOUNT_UPDATE user-data payload (the nested `a` object)."""
    a = d["a"]
    total_wallet_balance = sum((_dec(b["wb"]) for b in a.get("B", [])), start=Decimal(0))
    available_balance = sum((_dec(b["cw"]) for b in a.get("B", [])), start=Decimal(0))
    positions = []
    total_unrealized_pnl = Decimal(0)
    for p in a.get("P", []):
        side, qty = _side_and_qty(p["pa"])
        entry_price = _dec(p["ep"])
        unrealized_pnl = _dec(p.get("up", "0"))
        total_unrealized_pnl += unrealized_pnl
        positions.append(
            Position(
                symbol=p["s"],
                side=side,
                quantity=qty,
                entry_price=entry_price,
                mark_price=entry_price,  # not carried in this message; placeholder
                unrealized_pnl=unrealized_pnl,
                leverage=0,  # not carried in this message
                liquidation_price=None,
            )
        )
    state = AccountState(
        total_wallet_balance=total_wallet_balance,
        available_balance=available_balance,
        total_unrealized_pnl=total_unrealized_pnl,
        positions=positions,
        updated_at=_ms(d["E"]),
    )
    return AccountUpdate(state=state)
