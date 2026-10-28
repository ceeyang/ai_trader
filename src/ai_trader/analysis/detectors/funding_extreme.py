"""Funding-rate-extreme detector (design 5.6): flags a symbol's annualized funding
rate once its magnitude crosses `cfg.funding_annualized_threshold`, at most once per
`(symbol, next_funding_time)`."""

import time
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

from ai_trader.data.market_state import MarketState
from ai_trader.models import Direction, MarkPrice, Signal, new_id
from ai_trader.settings import DetectorConfig

_ANNUALIZATION_FACTOR = Decimal(3 * 365)


class FundingExtremeDetector:
    """Reads `cfg.funding_annualized_threshold` on every event, never at construction,
    so a later AutoTuner can retune it live (design 5.6)."""

    name = "funding_extreme"
    subscribes_to: tuple[type, ...] = (MarkPrice,)

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
        self._emitted: set[tuple[str, datetime]] = set()

    async def on_event(self, event: MarkPrice) -> list[Signal]:
        mp = event
        now = datetime.fromtimestamp(self._clock(), UTC)
        # Drop (symbol, next_funding_time) keys whose funding period has already
        # elapsed, so the set does not grow without bound across restarts of funding
        # cycles.
        self._emitted = {key for key in self._emitted if key[1] > now}

        threshold = self._cfg.funding_annualized_threshold
        annualized = mp.funding_rate * _ANNUALIZATION_FACTOR
        if abs(annualized) < threshold:
            return []

        key = (mp.symbol, mp.next_funding_time)
        if key in self._emitted:
            return []
        self._emitted.add(key)

        direction = Direction.BEARISH if annualized > 0 else Direction.BULLISH
        strength = min(1.0, float(abs(annualized) / (2 * threshold)))
        return [
            Signal(
                id=new_id(),
                detector=self.name,
                symbol=mp.symbol,
                direction=direction,
                strength=strength,
                created_at=now,
                expires_at=mp.next_funding_time,
                ref_price=mp.mark_price,
                rationale=f"annualized funding rate {annualized:.4f} crosses threshold {threshold}",
            )
        ]
