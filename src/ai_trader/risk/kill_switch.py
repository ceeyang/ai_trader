"""KillSwitch: the emergency flatten-everything stop (design 5.8).

`trigger()` sets a persistent kill-switch flag (so `RiskEngine` rejects every decision,
including CLOSE, from then on) and then best-effort cancels every open order and closes
every open position. A failure flattening one symbol is logged and does not stop the
rest of the sweep.
"""

import logging

from ai_trader.bus import EventBus
from ai_trader.execution.broker import Broker
from ai_trader.models import KillSwitchTriggered
from ai_trader.storage.db import Store

log = logging.getLogger(__name__)

_KEY = "kill_switch"


class KillSwitch:
    """Sets the persistent kill-switch flag and flattens every symbol with an open
    position or order, tolerating per-symbol failures (design 5.8)."""

    def __init__(self, store: Store, broker: Broker, bus: EventBus) -> None:
        self._store = store
        self._broker = broker
        self._bus = bus

    async def trigger(self, reason: str) -> None:
        await self._store.set_kv(_KEY, "1")
        positions = await self._broker.positions()
        symbols = set(positions.keys()) | await self._broker.open_order_symbols()
        for symbol in symbols:
            try:
                await self._broker.cancel_all(symbol)
                if symbol in positions:
                    await self._broker.close_position(symbol)
            except Exception:
                log.exception("kill switch: failed to flatten %s", symbol)
        self._bus.publish(KillSwitchTriggered(reason=reason))
        log.error("kill switch triggered: %s", reason)

    async def is_active(self) -> bool:
        return await self._store.get_kv(_KEY) == "1"

    async def reset(self) -> None:
        await self._store.set_kv(_KEY, "0")
