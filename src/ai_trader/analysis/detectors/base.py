"""Detector protocol and runner: subscribes detectors to the bus, persists each
emitted signal before publishing it, and never lets one detector's failure stop
the others (design 5.6)."""

import logging
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from ai_trader.bus import EventBus
from ai_trader.models import Signal
from ai_trader.storage.db import Store

log = logging.getLogger(__name__)


class Detector(Protocol):
    name: str
    subscribes_to: tuple[type, ...]

    # `Any`: each detector narrows it to the types in its `subscribes_to`, which is all
    # the runner ever routes to it.
    async def on_event(self, event: Any) -> list[Signal]: ...


class DetectorRunner:
    """Subscribes each detector to every type in its `subscribes_to`. Each `Signal` a
    detector returns is persisted via `store.insert_signal` before being published on
    `bus`. A detector that raises is logged and skipped; it never stops the other
    detectors or future events (design 5.6)."""

    def __init__(self, bus: EventBus, store: Store, detectors: list[Detector]) -> None:
        self._bus = bus
        self._store = store
        for detector in detectors:
            handler = self._make_handler(detector)
            for event_type in detector.subscribes_to:
                bus.subscribe(event_type, handler)

    def _make_handler(self, detector: Detector) -> Callable[[object], Awaitable[None]]:
        async def handle(event: object) -> None:
            try:
                signals = await detector.on_event(event)
            except Exception:
                log.exception("detector %s failed handling %s", detector.name, type(event).__name__)
                return
            for signal in signals:
                await self._store.insert_signal(signal)
                self._bus.publish(signal)

        return handle
