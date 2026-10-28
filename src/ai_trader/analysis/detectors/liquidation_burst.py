"""Liquidation-burst detector (design 5.6): sums each symbol's liquidation notional
inside a sliding window and flags a burst once one side's sum crosses
`cfg.liquidation_notional_threshold_usdt`, then holds off re-emitting for that symbol
during `cfg.liquidation_cooldown_s`."""

import time
from collections import defaultdict, deque
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from ai_trader.data.market_state import MarketState
from ai_trader.models import Direction, Liquidation, Side, Signal, new_id
from ai_trader.settings import DetectorConfig


class LiquidationBurstDetector:
    """Reads `cfg.liquidation_window_s`, `cfg.liquidation_notional_threshold_usdt` and
    `cfg.liquidation_cooldown_s` on every event, never at construction, so a later
    AutoTuner can retune them live (design 5.6)."""

    name = "liquidation_burst"
    subscribes_to: tuple[type, ...] = (Liquidation,)

    def __init__(
        self,
        cfg: DetectorConfig,
        state: MarketState,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._cfg = cfg
        self._state = state
        self._clock = clock
        self._window: dict[str, deque[tuple[float, Side, Decimal]]] = defaultdict(deque)
        self._cooldown_until: dict[str, float] = {}

    async def on_event(self, event: Liquidation) -> list[Signal]:
        liq = event
        now_ts = self._clock()
        window = self._window[liq.symbol]
        window.append((now_ts, liq.side, liq.notional))

        cutoff = now_ts - self._cfg.liquidation_window_s
        while window and window[0][0] < cutoff:
            window.popleft()

        threshold = self._cfg.liquidation_notional_threshold_usdt
        sell_notional = sum((n for _, side, n in window if side == Side.SELL), Decimal(0))
        buy_notional = sum((n for _, side, n in window if side == Side.BUY), Decimal(0))
        if sell_notional >= threshold:
            direction, total = Direction.BULLISH, sell_notional
        elif buy_notional >= threshold:
            direction, total = Direction.BEARISH, buy_notional
        else:
            return []

        cooldown_until = self._cooldown_until.get(liq.symbol)
        if cooldown_until is not None and now_ts < cooldown_until:
            return []
        self._cooldown_until[liq.symbol] = now_ts + self._cfg.liquidation_cooldown_s

        created_at = datetime.fromtimestamp(now_ts, UTC)
        mark = self._state.mark(liq.symbol)
        ref_price = mark.mark_price if mark is not None else liq.price
        strength = min(1.0, float(total / (2 * threshold)))
        return [
            Signal(
                id=new_id(),
                detector=self.name,
                symbol=liq.symbol,
                direction=direction,
                strength=strength,
                created_at=created_at,
                expires_at=created_at + timedelta(minutes=15),
                ref_price=ref_price,
                rationale=f"liquidation burst: {total} USDT notional ({direction.value})",
            )
        ]
