"""Domain enums, models, events and id helpers (design 5.2)."""

from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


# ---- enums -----------------------------------------------------------------
# Side/PositionSide/OrderType/OrderStatus mirror Binance's literal (uppercase)
# values; Direction/Horizon/Intent/OrderRole are internal and lowercase.


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class PositionSide(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_MARKET = "STOP_MARKET"
    TAKE_PROFIT_MARKET = "TAKE_PROFIT_MARKET"


class OrderStatus(str, Enum):
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    EXPIRED_IN_MATCH = "EXPIRED_IN_MATCH"


class Direction(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class Horizon(str, Enum):
    MINUTES = "minutes"
    HOURS = "hours"
    DAYS = "days"


class Intent(str, Enum):
    OPEN = "open"
    CLOSE = "close"


class OrderRole(str, Enum):
    ENTRY = "entry"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    CLOSE = "close"


# ---- market data -------------------------------------------------------


class MarkPrice(_Frozen):
    symbol: str
    mark_price: Decimal
    index_price: Decimal
    funding_rate: Decimal
    next_funding_time: datetime
    event_time: datetime


class Kline(_Frozen):
    symbol: str
    interval: str
    open_time: datetime
    close_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    is_closed: bool


class Liquidation(_Frozen):
    symbol: str
    side: Side
    price: Decimal
    qty: Decimal
    event_time: datetime

    @property
    def notional(self) -> Decimal:
        """price × qty. side == SELL means a long position was liquidated."""
        return self.price * self.qty


class NewsItem(_Frozen):
    id: str
    source: str
    author: str | None
    title: str
    text: str
    url: str | None
    published_at: datetime
    fetched_at: datetime
    raw: dict = {}


# ---- analysis -----------------------------------------------------------


class Sentiment(_Frozen):
    direction: Direction
    confidence: float
    symbols: list[str]
    horizon: Horizon
    rationale: str
    model: str


class Signal(_Frozen):
    id: str
    detector: str
    symbol: str
    direction: Direction
    strength: float
    created_at: datetime
    expires_at: datetime
    ref_price: Decimal
    rationale: str
    meta: dict = {}

    @property
    def signed_strength(self) -> float:
        if self.direction == Direction.BULLISH:
            return self.strength
        if self.direction == Direction.BEARISH:
            return -self.strength
        return 0.0


# ---- strategy / risk ------------------------------------------------------


class Decision(_Frozen):
    id: str
    symbol: str
    side: Side
    intent: Intent
    notional_usdt: Decimal
    score: float
    signal_ids: list[str]
    created_at: datetime
    stop_loss_pct: Decimal
    take_profit_pct: Decimal
    max_hold_s: int


class RiskVerdict(_Frozen):
    approved: bool
    reason: str | None = None
    adjusted_notional: Decimal | None = None


# ---- execution ------------------------------------------------------------


class OrderRequest(_Frozen):
    symbol: str
    side: Side
    type: OrderType
    quantity: Decimal | None = None
    price: Decimal | None = None
    stop_price: Decimal | None = None
    reduce_only: bool = False
    close_position: bool = False
    client_order_id: str
    time_in_force: str | None = None


class OrderResult(_Frozen):
    order_id: int
    client_order_id: str
    symbol: str
    side: Side
    type: OrderType
    status: OrderStatus
    orig_qty: Decimal
    executed_qty: Decimal
    avg_price: Decimal
    stop_price: Decimal | None
    reduce_only: bool
    close_position: bool
    update_time: datetime


class OrderRecord(_Frozen):
    client_order_id: str
    decision_id: str | None
    symbol: str
    side: Side
    type: OrderType
    role: OrderRole
    qty: Decimal | None
    price: Decimal | None
    stop_price: Decimal | None
    reduce_only: bool
    close_position: bool
    status: OrderStatus
    order_id: int | None
    avg_price: Decimal
    executed_qty: Decimal
    created_at: datetime
    updated_at: datetime


class Fill(_Frozen):
    order_id: int
    client_order_id: str
    symbol: str
    side: Side
    price: Decimal
    qty: Decimal
    realized_pnl: Decimal
    commission: Decimal
    event_time: datetime


# ---- account / positions --------------------------------------------------


class Position(_Frozen):
    symbol: str
    side: PositionSide
    quantity: Decimal  # absolute value
    entry_price: Decimal
    mark_price: Decimal
    unrealized_pnl: Decimal
    leverage: int
    liquidation_price: Decimal | None

    @property
    def notional(self) -> Decimal:
        return self.quantity * self.mark_price


class AccountState(_Frozen):
    total_wallet_balance: Decimal
    available_balance: Decimal
    total_unrealized_pnl: Decimal
    positions: list[Position]
    updated_at: datetime

    def open_positions(self) -> list[Position]:
        return [p for p in self.positions if p.quantity > 0]


# ---- events -----------------------------------------------------------


class DataStale(_Frozen):
    symbol: str
    age_s: float


class DataFresh(_Frozen):
    symbol: str


class ReconcileMismatch(_Frozen):
    symbol: str
    local_qty: Decimal
    remote_qty: Decimal


class KillSwitchTriggered(_Frozen):
    reason: str


class AccountUpdate(_Frozen):
    state: AccountState


# ---- id helpers -------------------------------------------------------


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return uuid4().hex


def new_client_order_id() -> str:
    """32-char id matching Binance's `^[\\.A-Z\\:/a-z0-9_-]{1,36}$`."""
    return "ait-" + uuid4().hex[:28]
