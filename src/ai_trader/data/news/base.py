"""News source protocol and a UTC-day-scoped request budget (design 5.5)."""

import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from ai_trader.models import NewsItem


class NewsSource(Protocol):
    name: str

    async def fetch(self) -> list[NewsItem]: ...


class DailyBudget:
    """Counts up to `limit` consumable units per UTC calendar day, as read from `clock()`.
    The counter resets the first time `clock()`'s UTC date differs from the day it was
    last touched (design 5.5)."""

    def __init__(self, limit: int, clock: Callable[[], float] = time.time) -> None:
        self._limit = limit
        self._clock = clock
        self._used = 0
        self._day = self._today()

    def _today(self):
        return datetime.fromtimestamp(self._clock(), tz=UTC).date()

    def _roll_if_new_day(self) -> None:
        today = self._today()
        if today != self._day:
            self._day = today
            self._used = 0

    def try_consume(self, n: int = 1) -> bool:
        self._roll_if_new_day()
        if self._used + n > self._limit:
            return False
        self._used += n
        return True

    def refund(self, n: int) -> None:
        self._roll_if_new_day()
        self._used = max(0, self._used - n)

    @property
    def remaining(self) -> int:
        self._roll_if_new_day()
        return self._limit - self._used
