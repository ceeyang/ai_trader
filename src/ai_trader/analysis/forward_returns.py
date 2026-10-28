"""Forward-return tracker: scores each persisted `Signal` against the mark price
`horizon_s` seconds after it fired (design 5.10).

`ret = (p1 - ref_price) / ref_price * sign(direction)`, so a correct BEARISH call on a
falling price is a positive return. Signals whose horizon has not elapsed yet, or for
which no mark sample lies within the store's tolerance of `created_at + horizon`, are
skipped and retried on the next tick; once `GIVE_UP_AFTER_S` has passed beyond the
horizon with still no sample (e.g. the process was down), a NULL sentinel is written so
the signal is not re-fetched forever. NEUTRAL signals carry no direction to score and get
the sentinel straight away.
"""

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta

from ai_trader.data.market_state import MarketState
from ai_trader.models import Direction
from ai_trader.storage.db import Store

log = logging.getLogger(__name__)

_SIGN = {Direction.BULLISH: 1, Direction.BEARISH: -1}
GIVE_UP_AFTER_S = 600


class ForwardReturnTracker:
    def __init__(
        self,
        store: Store,
        state: MarketState,
        *,
        horizons_s: Sequence[int] = (600, 3600, 14400),
        interval_s: float = 60,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._store = store
        self._state = state
        self._horizons_s = tuple(horizons_s)
        self._interval_s = interval_s
        self._clock = clock
        self._stop_event = asyncio.Event()

    async def tick(self) -> int:
        """Compute every forward return that has become due; returns how many were written."""
        now = datetime.fromtimestamp(self._clock(), UTC)
        written = 0
        for h in self._horizons_s:
            # `signals_missing_forward_return` keeps signals with `created_at + h <= before`,
            # so `before` is "now": only horizons that have fully elapsed are due.
            for s in await self._store.signals_missing_forward_return(h, before=now):
                sign = _SIGN.get(s.direction)
                if sign is None or s.ref_price == 0:
                    await self._store.insert_forward_return(s.id, h, None)
                    continue
                target = s.created_at + timedelta(seconds=h)
                p1 = await self._store.mark_at(s.symbol, target)
                if p1 is None:
                    if now > target + timedelta(seconds=GIVE_UP_AFTER_S):
                        log.info("forward return %s@%ss unscorable (no mark sample); giving up", s.id, h)
                        await self._store.insert_forward_return(s.id, h, None)
                    continue
                ret = float((p1 - s.ref_price) / s.ref_price) * sign
                await self._store.insert_forward_return(s.id, h, ret)
                written += 1
        return written

    async def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self.tick()
            except Exception:
                log.exception("forward-return tick failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval_s)

    async def stop(self) -> None:
        self._stop_event.set()
