"""`Broker` Protocol: the interface `ExecutionService`, the `RiskEngine`'s `KillSwitch`,
and both `PaperBroker`/`BinanceFuturesBroker` implementations share (design 5.9).

No implementation lives here — just the structural contract. `open_order_symbols` is not
part of the design-5.9 block; it is added so `KillSwitch` can discover symbols that have
open orders but no position yet (e.g. a resting protective order left after a position
was already closed some other way) and cancel those too.
"""

from typing import Protocol

from ai_trader.exchange.binance.filters import ExchangeInfo
from ai_trader.models import AccountState, OrderRequest, OrderResult, Position


class Broker(Protocol):
    exchange_info: ExchangeInfo

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def account(self) -> AccountState: ...

    async def positions(self) -> dict[str, Position]:
        """Only symbols with `quantity > 0`."""
        ...

    def positions_snapshot(self) -> dict[str, Position]:
        """Synchronous view of the broker's cached positions (`quantity > 0`), for callers
        such as `SignalAggregator` that cannot await."""
        ...

    async def ensure_symbol_setup(self, symbol: str, leverage: int, margin_type: str) -> None: ...

    async def submit(self, req: OrderRequest) -> OrderResult: ...

    async def cancel(self, symbol: str, client_order_id: str) -> OrderResult: ...

    async def cancel_all(self, symbol: str) -> None: ...

    async def close_position(self, symbol: str) -> OrderResult | None:
        """Reduce-only MARKET order that flattens the whole position; `None` if there is none."""
        ...

    async def open_order_symbols(self) -> set[str]:
        """Symbols that currently have at least one open order. Used by `KillSwitch`."""
        ...
