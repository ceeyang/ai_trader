"""Signal aggregator: turns Signals into open/close Decisions (design 5.7).

`score()` is a decayed, weighted sum of unexpired signals' `signed_strength` for a
symbol. `on_signal()` appends the incoming signal, scores the symbol, and — depending
on whether a position is already open — may emit an OPEN or CLOSE `Decision`, which is
persisted before it is published. `StrategyConfig` is mutable (the AutoTuner changes it
at runtime), so every field is read fresh on each call, never cached.
"""

import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from decimal import Decimal

from ai_trader.bus import EventBus
from ai_trader.data.market_state import MarketState
from ai_trader.models import Decision, Intent, Position, PositionSide, Side, Signal, new_id
from ai_trader.settings import StrategyConfig
from ai_trader.storage.db import Store

_TWO_DP = Decimal("0.01")


class SignalAggregator:
    """Aggregates `Signal`s per symbol into a score and, when it crosses the
    configured thresholds, an open/close `Decision` (design 5.7)."""

    def __init__(
        self,
        bus: EventBus,
        store: Store,
        state: MarketState,
        cfg: StrategyConfig,
        positions: Callable[[], Mapping[str, Position]],
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._bus = bus
        self._store = store
        self._state = state
        self._cfg = cfg
        self._positions = positions
        self._clock = clock
        self._signals: dict[str, list[Signal]] = {}
        self._last_decision_at: dict[str, float] = {}

    def score(self, symbol: str, now: float | None = None) -> float:
        """Decayed, weighted sum of unexpired signals' `signed_strength` for `symbol`.
        Expired signals are pruned from the internal list as a side effect."""
        now = now if now is not None else self._clock()
        half_life = self._cfg.signal_half_life_s
        weights = self._cfg.detector_weights
        alive = [s for s in self._signals.get(symbol, []) if s.expires_at.timestamp() > now]
        self._signals[symbol] = alive
        total = 0.0
        for s in alive:
            age = max(0.0, now - s.created_at.timestamp())
            weight = weights.get(s.detector, 0.0)
            total += s.signed_strength * weight * 0.5 ** (age / half_life)
        return total

    async def on_signal(self, s: Signal) -> Decision | None:
        symbol = s.symbol
        self._signals.setdefault(symbol, []).append(s)
        now = self._clock()
        score = self.score(symbol, now=now)
        contributing = [sig.id for sig in self._signals.get(symbol, [])]

        if symbol not in self._last_decision_at:
            stored = await self._store.last_decision_at(symbol)
            if stored is not None:
                self._last_decision_at[symbol] = stored.timestamp()

        pos = self._positions().get(symbol)
        if pos is not None and pos.quantity > 0:
            decision = self._close_decision(symbol, score, contributing, pos, now)
        else:
            decision = self._open_decision(symbol, score, contributing, now)

        if decision is None:
            return None
        await self._store.insert_decision(decision)
        self._last_decision_at[symbol] = now
        self._bus.publish(decision)
        return decision

    def _open_decision(
        self, symbol: str, score: float, signal_ids: list[str], now: float
    ) -> Decision | None:
        if abs(score) < self._cfg.entry_threshold:
            return None
        last = self._last_decision_at.get(symbol)
        if last is not None and now - last < self._cfg.cooldown_s:
            return None
        notional = (self._cfg.base_notional_usdt * Decimal(str(min(1.0, abs(score))))).quantize(_TWO_DP)
        return Decision(
            id=new_id(),
            symbol=symbol,
            side=Side.BUY if score > 0 else Side.SELL,
            intent=Intent.OPEN,
            notional_usdt=notional,
            score=score,
            signal_ids=signal_ids,
            created_at=self._to_dt(now),
            stop_loss_pct=self._cfg.stop_loss_pct,
            take_profit_pct=self._cfg.take_profit_pct,
            max_hold_s=self._cfg.max_hold_s,
        )

    def _close_decision(
        self, symbol: str, score: float, signal_ids: list[str], pos: Position, now: float
    ) -> Decision | None:
        exit_threshold = self._cfg.exit_threshold
        against = (pos.side == PositionSide.LONG and score <= -exit_threshold) or (
            pos.side == PositionSide.SHORT and score >= exit_threshold
        )
        if not against:
            return None
        return Decision(
            id=new_id(),
            symbol=symbol,
            side=Side.SELL if pos.side == PositionSide.LONG else Side.BUY,
            intent=Intent.CLOSE,
            notional_usdt=pos.notional,
            score=score,
            signal_ids=signal_ids,
            created_at=self._to_dt(now),
            stop_loss_pct=self._cfg.stop_loss_pct,
            take_profit_pct=self._cfg.take_profit_pct,
            max_hold_s=self._cfg.max_hold_s,
        )

    @staticmethod
    def _to_dt(now: float) -> datetime:
        return datetime.fromtimestamp(now, tz=UTC)

    async def start(self) -> None:
        self._bus.subscribe(Signal, self.on_signal)
