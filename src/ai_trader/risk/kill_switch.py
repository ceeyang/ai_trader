"""KillSwitch: the emergency flatten-everything stop (design 5.8).

`trigger()` sets a persistent kill-switch flag (so `RiskEngine` rejects every decision,
including CLOSE, from then on) and then best-effort cancels every open order and closes
every open position. This is the last line of capital protection, so it is written to
degrade rather than abort: discovering positions and discovering open-order symbols are
each independently fault-tolerant (a failure on one side still lets the other side's
symbols get flattened), cancelling and closing a given symbol are independent attempts
(a failed cancel must not skip the close), and a failure on one symbol must not stop the
rest of the sweep. The flag write, the final `KillSwitchTriggered` publish and the ERROR
log happen unconditionally, even if every single broker call above failed.
"""

import logging

from ai_trader.bus import EventBus
from ai_trader.execution.broker import Broker
from ai_trader.models import KillSwitchTriggered, Position
from ai_trader.storage.db import Store

log = logging.getLogger(__name__)

_KEY = "kill_switch"


class KillSwitch:
    """Sets the persistent kill-switch flag and flattens every symbol with an open
    position or order, tolerating per-symbol and per-discovery-call failures (design 5.8)."""

    def __init__(self, store: Store, broker: Broker, bus: EventBus) -> None:
        self._store = store
        self._broker = broker
        self._bus = bus

    async def trigger(self, reason: str) -> None:
        await self._store.set_kv(_KEY, "1")
        try:
            positions = await self._positions_or_empty()
            order_symbols = await self._open_order_symbols_or_empty()
            for symbol in set(positions) | order_symbols:
                await self._flatten(symbol, has_position=symbol in positions)
        finally:
            self._bus.publish(KillSwitchTriggered(reason=reason))
            log.error("kill switch triggered: %s", reason)

    async def _positions_or_empty(self) -> dict[str, Position]:
        try:
            return await self._broker.positions()
        except Exception as exc:
            log.exception("kill switch: failed to fetch open positions: %s", type(exc).__name__)
            return {}

    async def _open_order_symbols_or_empty(self) -> set[str]:
        try:
            return await self._broker.open_order_symbols()
        except Exception as exc:
            log.exception("kill switch: failed to fetch open order symbols: %s", type(exc).__name__)
            return set()

    async def _flatten(self, symbol: str, *, has_position: bool) -> None:
        """Cancel and close are independent attempts: a failed cancel must not skip the
        close, and either failing must not stop the rest of the sweep."""
        try:
            await self._broker.cancel_all(symbol)
        except Exception as exc:
            log.exception("kill switch: cancel_all failed for %s: %s", symbol, type(exc).__name__)
        if has_position:
            try:
                await self._broker.close_position(symbol)
            except Exception as exc:
                log.exception(
                    "kill switch: close_position failed for %s: %s", symbol, type(exc).__name__
                )

    async def is_active(self) -> bool:
        return await self._store.get_kv(_KEY) == "1"

    async def reset(self) -> None:
        await self._store.set_kv(_KEY, "0")
