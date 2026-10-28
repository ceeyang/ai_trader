"""Shared test constructors (design 5.10 brief, Task 5). Later tasks import by these names."""

import asyncio
import json
import pathlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from ai_trader.bus import EventBus
from ai_trader.data.market_state import MarketState
from ai_trader.exchange.binance.parsers import parse_exchange_info
from ai_trader.models import (
    AccountState,
    Decision,
    Direction,
    Fill,
    Intent,
    Liquidation,
    MarkPrice,
    NewsItem,
    OrderRecord,
    OrderRole,
    OrderStatus,
    OrderType,
    Position,
    PositionSide,
    Side,
    Signal,
    new_id,
)
from ai_trader.storage.db import Store

T0 = datetime(2026, 10, 29, tzinfo=UTC)

FX = pathlib.Path(__file__).parent / "fixtures" / "binance"


def fx(name: str):
    return json.loads((FX / name).read_text())


async def _append(lst, e):
    lst.append(e)


def make_news(id: str, title: str = "t", text: str = "x", source: str = "rss") -> NewsItem:
    return NewsItem(
        id=id,
        source=source,
        author=None,
        title=title,
        text=text,
        url=None,
        published_at=T0,
        fetched_at=T0,
    )


def make_signal(
    id: str,
    *,
    detector: str = "funding_extreme",
    symbol: str = "BTCUSDT",
    direction: Direction = Direction.BULLISH,
    strength: float = 0.7,
    created_at: datetime = T0,
    expires_at: datetime = T0 + timedelta(hours=1),
    ref_price: Decimal = Decimal("80000"),  # noqa: FURB157
) -> Signal:
    return Signal(
        id=id,
        detector=detector,
        symbol=symbol,
        direction=direction,
        strength=strength,
        created_at=created_at,
        expires_at=expires_at,
        ref_price=ref_price,
        rationale="test",
    )


def make_fill(
    cid: str,
    *,
    realized_pnl: Decimal = Decimal("0"),  # noqa: FURB157
    event_time: datetime = T0,
    symbol: str = "BTCUSDT",
) -> Fill:
    return Fill(
        order_id=1,
        client_order_id=cid,
        symbol=symbol,
        side=Side.BUY,
        price=Decimal("80000"),  # noqa: FURB157
        qty=Decimal("0.001"),
        realized_pnl=realized_pnl,
        commission=Decimal(0),
        event_time=event_time,
    )


def make_order_record(
    cid: str,
    *,
    role: OrderRole,
    status: OrderStatus,
    symbol: str = "BTCUSDT",
) -> OrderRecord:
    return OrderRecord(
        client_order_id=cid,
        decision_id=None,
        symbol=symbol,
        side=Side.BUY,
        type=OrderType.MARKET,
        role=role,
        qty=Decimal("0.001"),
        price=None,
        stop_price=None,
        reduce_only=False,
        close_position=False,
        status=status,
        order_id=None,
        avg_price=Decimal(0),
        executed_qty=Decimal(0),
        created_at=T0,
        updated_at=T0,
    )


def make_mark_price(
    *,
    symbol: str = "BTCUSDT",
    mark: Decimal = Decimal("80000"),  # noqa: FURB157
    funding_rate: Decimal = Decimal("0.0001"),
    next_funding_time: datetime = T0 + timedelta(hours=8),
) -> MarkPrice:
    return MarkPrice(
        symbol=symbol,
        mark_price=mark,
        index_price=mark,
        funding_rate=funding_rate,
        next_funding_time=next_funding_time,
        event_time=T0,
    )


def make_liq(side: Side, *, price: Decimal, qty: Decimal, symbol: str = "BTCUSDT") -> Liquidation:
    return Liquidation(symbol=symbol, side=side, price=price, qty=qty, event_time=T0)


def make_position(
    side: PositionSide,
    qty: Decimal,
    mark: Decimal,
    *,
    symbol: str = "BTCUSDT",
    entry: Decimal | None = None,
) -> Position:
    entry_price = entry if entry is not None else mark
    if side == PositionSide.LONG:
        unrealized = (mark - entry_price) * qty
    elif side == PositionSide.SHORT:
        unrealized = (entry_price - mark) * qty
    else:
        unrealized = Decimal(0)
    return Position(
        symbol=symbol,
        side=side,
        quantity=qty,
        entry_price=entry_price,
        mark_price=mark,
        unrealized_pnl=unrealized,
        leverage=10,
        liquidation_price=None,
    )


def make_account(*, wallet: Decimal, positions: list[Position]) -> AccountState:
    total_unrealized = sum((p.unrealized_pnl for p in positions), Decimal(0))
    return AccountState(
        total_wallet_balance=wallet,
        available_balance=wallet,
        total_unrealized_pnl=total_unrealized,
        positions=positions,
        updated_at=T0,
    )


def make_decision(
    *,
    symbol: str = "BTCUSDT",
    side: Side = Side.BUY,
    intent: Intent = Intent.OPEN,
    notional: Decimal = Decimal("100"),  # noqa: FURB157
) -> Decision:
    return Decision(
        id=new_id(),
        symbol=symbol,
        side=side,
        intent=intent,
        notional_usdt=notional,
        score=1.0,
        signal_ids=[],
        created_at=T0,
        stop_loss_pct=Decimal("0.01"),
        take_profit_pct=Decimal("0.02"),
        max_hold_s=3600,
    )


def make_decision_model(
    *,
    created_at: datetime = T0,
    symbol: str = "BTCUSDT",
    side: Side = Side.BUY,
    intent: Intent = Intent.OPEN,
) -> Decision:
    """A `Decision` with the given `created_at` (unique id each call)."""
    return make_decision(symbol=symbol, side=side, intent=intent).model_copy(update={"created_at": created_at})


async def seed_effectiveness(
    st: Store, detector: str, *, horizon_s: int, n: int, hit_rate: float, mean_ret: float
) -> None:
    """Insert `n` signals for `detector` plus their `horizon_s` forward returns so that
    `st.effectiveness()` reports `n`, a hit rate of `round(n*hit_rate)/n` and `mean_ret`:
    `k = round(n*hit_rate)` positive returns, the rest negative, averaging `mean_ret`."""
    k = round(n * hit_rate)
    if k in (0, n):
        if (k == 0 and mean_ret >= 0) or (k == n and mean_ret <= 0):
            raise ValueError("mean_ret incompatible with an all-negative/all-positive sample")
        rets = [mean_ret] * n
    else:
        spread = (abs(mean_ret) + 0.01) * n
        pos = mean_ret + spread * (n - k) / k
        neg = mean_ret - spread
        rets = [pos] * k + [neg] * (n - k)
    created = T0 - timedelta(days=2)  # old enough not to count as recent activity
    for i, ret in enumerate(rets):
        sid = f"seed-{detector}-{horizon_s}-{i}-{new_id()}"
        await st.insert_signal(make_signal(sid, detector=detector, created_at=created, expires_at=created))
        await st.insert_forward_return(sid, horizon_s, ret)


@pytest.fixture
async def bus():
    b = EventBus()
    await b.start()
    yield b
    await b.stop()


@pytest.fixture
async def st(tmp_path):
    store = Store(tmp_path / "t.db")
    await store.open()
    yield store
    await store.close()


@pytest.fixture
def state_fresh():
    """A MarketState with a constant clock and current marks for BTCUSDT/ETHUSDT,
    so `age_s` is 0 for both regardless of when the test runs."""
    state = MarketState(clock=lambda: 0.0)
    state.update_mark(make_mark_price(symbol="BTCUSDT"))
    state.update_mark(make_mark_price(symbol="ETHUSDT"))
    return state


@pytest.fixture
def state_stale():
    """An empty MarketState: `age_s` returns None for every symbol."""
    return MarketState()


@pytest.fixture
def state():
    """An empty MarketState with the default clock."""
    return MarketState()


@pytest.fixture
def exchange_info():
    return parse_exchange_info(fx("exchange_info.json"))


class _FakeWS:
    """Stands in for `BinanceFuturesWS`: `run()` blocks until `stop()`; no network."""

    def __init__(self, url, handler) -> None:
        self.url = url
        self.handler = handler
        self._stopped = asyncio.Event()

    async def run(self) -> None:
        await self._stopped.wait()

    async def stop(self) -> None:
        self._stopped.set()


def fake_ws_factory(url, handler):
    """`ws_factory` for `BinanceFuturesBroker`: records `handler` under `url` so a test
    can feed user-stream messages straight into it."""
    fake_ws_factory.handlers[url] = handler
    return _FakeWS(url, handler)


fake_ws_factory.handlers = {}


class FakeRest:
    """Stands in for `BinanceFuturesRest` in wiring tests: no network."""

    def __init__(self, exchange_info) -> None:
        self._exchange_info = exchange_info
        self.closed = False

    async def exchange_info(self):
        return self._exchange_info

    async def sync_time(self) -> int:
        return 0

    async def premium_index(self, symbol: str) -> MarkPrice:
        return make_mark_price(symbol=symbol)

    async def aclose(self) -> None:
        self.closed = True
