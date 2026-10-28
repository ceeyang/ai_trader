"""In-memory latest market state per symbol (design 5.5)."""

import time
from collections.abc import Callable

from ai_trader.models import MarkPrice


class MarketState:
    """Holds the latest `MarkPrice` per symbol plus the monotonic time it arrived."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._marks: dict[str, MarkPrice] = {}
        self._updated_at: dict[str, float] = {}

    def update_mark(self, mp: MarkPrice) -> None:
        self._marks[mp.symbol] = mp
        self._updated_at[mp.symbol] = self._clock()

    def mark(self, symbol: str) -> MarkPrice | None:
        return self._marks.get(symbol)

    def age_s(self, symbol: str, now: float | None = None) -> float | None:
        """Seconds since the last update for `symbol`, or None when there is no data."""
        updated_at = self._updated_at.get(symbol)
        if updated_at is None:
            return None
        return (now if now is not None else self._clock()) - updated_at
