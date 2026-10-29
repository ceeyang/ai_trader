"""KillSwitch: the emergency flatten-everything stop (design 5.8).

`trigger()` sets a persistent kill-switch flag (so `RiskEngine` rejects every decision,
including CLOSE, from then on) and then best-effort cancels every open order and closes
every open position. This is the last line of capital protection, so it is written to
degrade rather than abort: discovering positions and discovering open-order symbols are
each independently fault-tolerant (a failure on one side still lets the other side's
symbols get flattened), cancelling and closing a given symbol are independent attempts
(a failed cancel must not skip the close), and a failure on one symbol must not stop the
rest of the sweep. The final `KillSwitchTriggered` publish and the ERROR log happen
unconditionally, even if every single broker call above failed; a failed flag write is
logged and the sweep still runs. Every failure is also appended to `last_errors` (reset
at the start of each `trigger`), so a caller such as `ai-trader kill` can report it.

`triggered` is True once `trigger()` ran in this process; the App's control loop uses
it so an externally set kv flag flattens the in-process broker exactly once.
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
        self.triggered = False
        self.last_errors: list[str] = []

    async def trigger(self, reason: str) -> None:
        self.triggered = True
        self.last_errors = []
        try:
            await self._store.set_kv(_KEY, "1")
        except Exception as exc:
            log.exception("kill switch: persisting the flag failed: %s", type(exc).__name__)
            self.last_errors.append(f"persist flag: {type(exc).__name__}: {exc}")
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
            self.last_errors.append(f"fetch positions: {type(exc).__name__}: {exc}")
            return {}

    async def _open_order_symbols_or_empty(self) -> set[str]:
        try:
            return await self._broker.open_order_symbols()
        except Exception as exc:
            log.exception("kill switch: failed to fetch open order symbols: %s", type(exc).__name__)
            self.last_errors.append(f"fetch open orders: {type(exc).__name__}: {exc}")
            return set()

    async def _flatten(self, symbol: str, *, has_position: bool) -> None:
        """Cancel and close are independent attempts: a failed cancel must not skip the
        close, and either failing must not stop the rest of the sweep. A broker that can
        tell it cannot close `symbol` right now (`can_close`, e.g. paper without a mark)
        leaves that symbol untouched — its SL/TP keep protecting the position — and the
        failure is recorded so the caller can retry."""
        can_close = getattr(self._broker, "can_close", None)
        if has_position and can_close is not None and not can_close(symbol):
            log.error("kill switch: %s cannot be closed yet; leaving its protective orders resting", symbol)
            self.last_errors.append(f"{symbol} close_position: not closable yet (no mark price)")
            return
        try:
            await self._broker.cancel_all(symbol)
        except Exception as exc:
            log.exception("kill switch: cancel_all failed for %s: %s", symbol, type(exc).__name__)
            self.last_errors.append(f"{symbol} cancel_all: {type(exc).__name__}: {exc}")
        if has_position:
            try:
                await self._broker.close_position(symbol)
            except Exception as exc:
                log.exception(
                    "kill switch: close_position failed for %s: %s", symbol, type(exc).__name__
                )
                self.last_errors.append(f"{symbol} close_position: {type(exc).__name__}: {exc}")

    async def is_active(self) -> bool:
        return await self._store.get_kv(_KEY) == "1"

    async def reset(self) -> None:
        await self.reset_flag(self._store)
        self.triggered = False

    @staticmethod
    async def reset_flag(store: Store) -> None:
        """Clear the persistent flag (kv `kill_switch=0`); usable without a broker
        (`ai-trader kill --reset`)."""
        await store.set_kv(_KEY, "0")
