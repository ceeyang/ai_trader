"""Volume-confirmed breakout detector: on each CLOSED kline, flags a close beyond the
highest high (BULLISH) or lowest low (BEARISH) of the previous `cfg.breakout_lookback`
candles, provided the candle's volume is at least `cfg.breakout_volume_mult` × the
lookback's mean volume and the close clears the level by `cfg.breakout_min_move_pct` %.
At most one signal per symbol per `cfg.breakout_cooldown_s`."""

import time
from collections import defaultdict, deque
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from ai_trader.data.market_state import MarketState
from ai_trader.models import Direction, Kline, Signal, new_id
from ai_trader.settings import DetectorConfig


class BreakoutDetector:
    """Reads every `cfg.breakout_*` field on each event, never at construction, so a
    later AutoTuner can retune them live."""

    name = "breakout"
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
        # (open_time, high, low, volume) of previous closed candles, per (symbol, interval).
        self._history: dict[tuple[str, str], deque[tuple[datetime, Decimal, Decimal, Decimal]]] = defaultdict(deque)
        self._cooldown_until: dict[str, float] = {}

    async def on_event(self, event: Kline) -> list[Signal]:
        k = event
        if not k.is_closed:
            return []
        hist = self._history[(k.symbol, k.interval)]
        if hist and k.open_time <= hist[-1][0]:
            return []  # duplicate / out-of-order candle
        lookback = max(1, int(self._cfg.breakout_lookback))
        while len(hist) > lookback:
            hist.popleft()
        try:
            return self._evaluate(k, hist, lookback)
        finally:
            hist.append((k.open_time, k.high, k.low, k.volume))
            while len(hist) > lookback:
                hist.popleft()

    def _evaluate(
        self,
        k: Kline,
        hist: deque[tuple[datetime, Decimal, Decimal, Decimal]],
        lookback: int,
    ) -> list[Signal]:
        if len(hist) < lookback:
            return []
        level_high = max(h for _, h, _, _ in hist)
        level_low = min(lo for _, _, lo, _ in hist)
        mean_vol = sum((v for _, _, _, v in hist), Decimal(0)) / len(hist)
        if mean_vol <= 0:
            return []
        vol_ratio = float(k.volume / mean_vol)
        if vol_ratio < self._cfg.breakout_volume_mult:
            return []

        min_move = Decimal(str(self._cfg.breakout_min_move_pct)) / 100
        if k.close > level_high and (k.close - level_high) / level_high >= min_move:
            direction, level = Direction.BULLISH, level_high
        elif k.close < level_low and (level_low - k.close) / level_low >= min_move:
            direction, level = Direction.BEARISH, level_low
        else:
            return []

        now_ts = self._clock()
        cooldown_until = self._cooldown_until.get(k.symbol)
        if cooldown_until is not None and now_ts < cooldown_until:
            return []
        self._cooldown_until[k.symbol] = now_ts + self._cfg.breakout_cooldown_s

        created_at = datetime.fromtimestamp(now_ts, UTC)
        mark = self._state.mark(k.symbol)
        ref_price = mark.mark_price if mark is not None else k.close
        strength = min(1.0, max(0.5, 0.5 + 0.5 * (vol_ratio - 1) / 2))
        side = "above high" if direction == Direction.BULLISH else "below low"
        return [
            Signal(
                id=new_id(),
                detector=self.name,
                symbol=k.symbol,
                direction=direction,
                strength=strength,
                created_at=created_at,
                expires_at=created_at + timedelta(seconds=self._cfg.breakout_ttl_s),
                ref_price=ref_price,
                rationale=(
                    f"{k.interval} close {k.close} broke {side} {level} of last {lookback} candles "
                    f"on {vol_ratio:.2f}x mean volume"
                ),
            )
        ]
