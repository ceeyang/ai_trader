"""Z-score mean-reversion detector: on each CLOSED kline, keeps the last
`cfg.mr_lookback` closes (current candle included) and computes z = (close − mean) /
population stdev. z ≥ `cfg.mr_z_entry` → BEARISH (expect a pull back down), z ≤
−`cfg.mr_z_entry` → BULLISH. At most one signal per symbol per `cfg.mr_cooldown_s`."""

import statistics
import time
from collections import defaultdict, deque
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from ai_trader.data.market_state import MarketState
from ai_trader.models import Direction, Kline, Signal, new_id
from ai_trader.settings import DetectorConfig


class MeanReversionDetector:
    """Reads every `cfg.mr_*` field on each event, never at construction, so a later
    AutoTuner can retune them live."""

    name = "mean_reversion"
    subscribes_to: tuple[type, ...] = (Kline,)

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
        self._closes: dict[tuple[str, str], deque[tuple[datetime, float]]] = defaultdict(deque)
        self._cooldown_until: dict[str, float] = {}

    async def on_event(self, event: Kline) -> list[Signal]:
        k = event
        if not k.is_closed:
            return []
        window = self._closes[(k.symbol, k.interval)]
        if window and k.open_time <= window[-1][0]:
            return []  # duplicate / out-of-order candle
        window.append((k.open_time, float(k.close)))
        lookback = max(2, int(self._cfg.mr_lookback))
        while len(window) > lookback:
            window.popleft()
        if len(window) < lookback:
            return []

        closes = [c for _, c in window]
        mean = statistics.fmean(closes)
        stdev = statistics.pstdev(closes, mean)
        if stdev <= 0:
            return []
        z = (float(k.close) - mean) / stdev
        z_entry = float(self._cfg.mr_z_entry)
        if z >= z_entry:
            direction = Direction.BEARISH
        elif z <= -z_entry:
            direction = Direction.BULLISH
        else:
            return []

        now_ts = self._clock()
        cooldown_until = self._cooldown_until.get(k.symbol)
        if cooldown_until is not None and now_ts < cooldown_until:
            return []
        self._cooldown_until[k.symbol] = now_ts + self._cfg.mr_cooldown_s

        created_at = datetime.fromtimestamp(now_ts, UTC)
        mark = self._state.mark(k.symbol)
        ref_price = mark.mark_price if mark is not None else k.close
        strength = min(1.0, 0.5 + (abs(z) - z_entry) / 2)
        return [
            Signal(
                id=new_id(),
                detector=self.name,
                symbol=k.symbol,
                direction=direction,
                strength=strength,
                created_at=created_at,
                expires_at=created_at + timedelta(seconds=self._cfg.mr_ttl_s),
                ref_price=ref_price,
                rationale=(
                    f"{k.interval} close {k.close} z={z:.2f} vs {lookback}-candle "
                    f"mean {mean:.6g} stdev {stdev:.6g}"
                ),
            )
        ]
