"""News poller: fetches each source on its own schedule and publishes only the items
the store has not seen before (design 5.5)."""

import asyncio
import contextlib
import logging
from collections.abc import Sequence

from ai_trader.bus import EventBus
from ai_trader.data.news.base import NewsSource
from ai_trader.storage.db import Store

log = logging.getLogger(__name__)


class NewsPoller:
    """Each `(source, interval_s)` pair in `sources` is fetched once per `poll_once()`
    call, or repeatedly by `run()` on its own `interval_s` cadence until `stop()`. An
    item is published on `bus` only if `store.insert_news` reports it as new, so
    re-fetching the same item (e.g. on the next poll) never re-publishes it. A source
    that raises is logged and skipped; it never stops the other sources (design 5.5)."""

    def __init__(self, bus: EventBus, store: Store, sources: Sequence[tuple[NewsSource, int]]) -> None:
        self._bus = bus
        self._store = store
        self._sources = sources
        self._stop_event = asyncio.Event()

    async def poll_once(self) -> None:
        for source, _interval_s in self._sources:
            await self._fetch_and_publish(source)

    async def run(self) -> None:
        self._stop_event.clear()
        tasks = [
            asyncio.create_task(self._run_source(source, interval_s))
            for source, interval_s in self._sources
        ]
        await self._stop_event.wait()
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def stop(self) -> None:
        self._stop_event.set()

    async def _run_source(self, source: NewsSource, interval_s: float) -> None:
        while not self._stop_event.is_set():
            await self._fetch_and_publish(source)
            # Interruptible sleep: stop() sets _stop_event so this returns immediately
            # instead of blocking for the full interval (as in market_feed.py).
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop_event.wait(), timeout=interval_s)

    async def _fetch_and_publish(self, source: NewsSource) -> None:
        try:
            items = await source.fetch()
        except Exception:
            log.exception("news source %s failed", getattr(source, "name", source))
            return
        for item in items:
            if await self._store.insert_news(item):
                self._bus.publish(item)
