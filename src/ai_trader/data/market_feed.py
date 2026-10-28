"""Market data feed, staleness watchdog and mark-price sampler (design 5.5)."""

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime, timedelta

from ai_trader.bus import EventBus
from ai_trader.data.market_state import MarketState
from ai_trader.exchange.binance.parsers import parse_force_order, parse_kline, parse_mark_price
from ai_trader.exchange.binance.ws import BinanceFuturesWS, market_stream_url
from ai_trader.models import DataFresh, DataStale, MarkPrice, utc_now
from ai_trader.storage.db import Store

log = logging.getLogger(__name__)


def build_stream_names(symbols: Sequence[str], kline_intervals: Sequence[str] = ("1m",)) -> list[str]:
    """Combined-stream names for each symbol: mark price, one per kline interval, liquidations."""
    streams: list[str] = []
    for symbol in symbols:
        s = symbol.lower()
        streams.append(f"{s}@markPrice@1s")
        streams.extend(f"{s}@kline_{interval}" for interval in kline_intervals)
        streams.append(f"{s}@forceOrder")
    return streams


class MarketFeed:
    """Connects to Binance's combined market stream, publishing typed events on `bus`
    and keeping `state` updated with each mark price (design 5.5)."""

    def __init__(
        self,
        bus: EventBus,
        state: MarketState,
        ws_url: str,
        symbols: Sequence[str],
        *,
        ws_factory: Callable[[str, Callable[[dict], Awaitable[None]]], object] | None = None,
    ) -> None:
        self._bus = bus
        self._state = state
        url = market_stream_url(ws_url, build_stream_names(symbols))
        factory = ws_factory or BinanceFuturesWS
        self._ws = factory(url, self.handle)

    async def handle(self, msg: dict) -> None:
        event_type = msg.get("e")
        if event_type == "markPriceUpdate":
            mp = parse_mark_price(msg)
            self._state.update_mark(mp)
            self._bus.publish(mp)
        elif event_type == "kline":
            self._bus.publish(parse_kline(msg))
        elif event_type == "forceOrder":
            self._bus.publish(parse_force_order(msg))
        else:
            log.debug("MarketFeed received unknown event type %r, ignoring", event_type)

    async def run(self) -> None:
        await self._ws.run()

    async def stop(self) -> None:
        await self._ws.stop()


class StalenessWatchdog:
    """Watches `state` for symbols going stale (no data, or older than `max_age_s`) or
    becoming fresh again, publishing `DataStale`/`DataFresh` exactly once per transition
    (design 5.5)."""

    def __init__(
        self,
        bus: EventBus,
        state: MarketState,
        symbols: Sequence[str],
        max_age_s: float,
        *,
        check_interval_s: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._bus = bus
        self._state = state
        self._symbols = symbols
        self._max_age_s = max_age_s
        self._check_interval_s = check_interval_s
        self._clock = clock
        self._stale: set[str] = set()
        self._stop_event = asyncio.Event()

    def is_stale(self, symbol: str) -> bool:
        return symbol in self._stale

    def _check_once(self) -> None:
        now = self._clock()
        for symbol in self._symbols:
            age = self._state.age_s(symbol, now)
            if age is None:
                age = float("inf")
            if age > self._max_age_s:
                if symbol not in self._stale:
                    self._stale.add(symbol)
                    self._bus.publish(DataStale(symbol=symbol, age_s=age))
            elif symbol in self._stale:
                self._stale.discard(symbol)
                self._bus.publish(DataFresh(symbol=symbol))

    async def run(self) -> None:
        while not self._stop_event.is_set():
            self._check_once()
            # Interruptible sleep: stop() sets _stop_event so this returns immediately
            # instead of blocking for the full check interval (as in ws.py's backoff sleep).
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._check_interval_s)

    async def stop(self) -> None:
        self._stop_event.set()


class MarkPriceSampler:
    """Subscribes to `MarkPrice` on construction and writes at most one sample per
    symbol per `interval_s` to `store`, gated by `clock` (design 5.5).

    The gate is keyed off `clock()` (monotonic by default) so it is immune to wall-clock
    adjustments; the persisted sample timestamp is the wall-clock write time, since the
    `mark_samples` table's primary key is `(symbol, ts)` and an upstream `MarkPrice.event_time`
    that repeats (as it legitimately can for synthetic/replayed data) would otherwise collide
    and silently replace the previous sample instead of adding a new one. The wall-clock time
    is nudged forward by a microsecond when it would not be strictly greater than the previous
    write's timestamp, so two writes close enough to land on the same clock tick still get
    distinct, monotonically increasing timestamps.
    """

    def __init__(
        self,
        bus: EventBus,
        store: Store,
        interval_s: float = 10,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._store = store
        self._interval_s = interval_s
        self._clock = clock
        self._last_write_at: dict[str, float] = {}
        self._last_ts: datetime | None = None
        bus.subscribe(MarkPrice, self._on_mark_price)

    async def _on_mark_price(self, mp: MarkPrice) -> None:
        now = self._clock()
        last = self._last_write_at.get(mp.symbol)
        if last is not None and now - last < self._interval_s:
            return
        self._last_write_at[mp.symbol] = now
        ts = utc_now()
        if self._last_ts is not None and ts <= self._last_ts:
            ts = self._last_ts + timedelta(microseconds=1)
        self._last_ts = ts
        await self._store.insert_mark_sample(mp.symbol, ts, mp.mark_price)
