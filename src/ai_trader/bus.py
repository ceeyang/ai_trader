"""Typed, per-subscription queued event bus (design 5.3)."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class _Subscription:
    event_type: type
    handler: Callable[[object], Awaitable[None]]
    queue: asyncio.Queue
    task: asyncio.Task | None = None
    in_flight: int = 0


class EventBus:
    def __init__(self) -> None:
        self._subs: list[_Subscription] = []
        self.dropped: dict[str, int] = {}

    def subscribe(
        self,
        event_type: type[T],
        handler: Callable[[T], Awaitable[None]],
        *,
        maxsize: int = 10_000,
    ) -> None:
        self._subs.append(
            _Subscription(event_type=event_type, handler=handler, queue=asyncio.Queue(maxsize=maxsize))
        )

    def publish(self, event: object) -> None:
        for sub in self._subs:
            if not isinstance(event, sub.event_type):
                continue
            try:
                sub.queue.put_nowait(event)
            except asyncio.QueueFull:
                sub.queue.get_nowait()
                sub.queue.put_nowait(event)
                key = f"{sub.event_type.__name__}:{sub.handler.__qualname__}"
                self.dropped[key] = self.dropped.get(key, 0) + 1

    async def start(self) -> None:
        for sub in self._subs:
            sub.task = asyncio.create_task(self._worker(sub))

    async def stop(self) -> None:
        for sub in self._subs:
            if sub.task is not None:
                sub.task.cancel()
        for sub in self._subs:
            if sub.task is not None:
                try:
                    await sub.task
                except asyncio.CancelledError:
                    pass
                sub.task = None

    async def drain(self, timeout_s: float = 2.0) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s
        while loop.time() < deadline:
            if all(sub.queue.empty() and sub.in_flight == 0 for sub in self._subs):
                return
            await asyncio.sleep(0.01)

    async def _worker(self, sub: _Subscription) -> None:
        while True:
            event = await sub.queue.get()
            sub.in_flight += 1
            try:
                await sub.handler(event)
            except Exception:
                log.exception("event handler %s failed", sub.handler.__qualname__)
            finally:
                sub.in_flight -= 1
                sub.queue.task_done()
