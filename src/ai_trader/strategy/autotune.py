"""AutoTuner: nudges strategy/detector parameters from live results (design 5.12).

User requirement (2026-10-29): "如果结果出现偏差，或者实测数据不好，你需要自动调整策略。"

Every `interval_s` the tuner runs `tick()`, which evaluates four rules in this order, each
moving its fields at most one step per tick:

1. `activity_floor` — fewer than 3 signals and no decision in the last `activity_window_s`:
   liquidation threshold ×0.7 (≥ 5000), news confidence −0.05 (≥ 0.3), funding threshold
   ×0.8 (≥ 0.05), `entry_threshold` −0.05 (≥ 0.3).
2. `detector_quality` — for each detector with n ≥ 20 one-hour forward returns: hit rate
   < 0.40 and mean < 0 → weight −0.25 (≥ 0, 0 disables it); hit rate ≥ 0.55 and mean > 0 →
   weight +0.1 (≤ 1.5).
3. `loss_brake` — today's realized pnl ≤ −2 % of the day's starting equity (skipped while
   `day_start_equity:<UTC date>` is missing) → `base_notional_usdt` ×0.5 (≥ 20) and
   `entry_threshold` +0.1 (≤ 0.9); ≥ +2 % with the notional below the default 100 → ×1.25
   (≤ 100).
4. `overtrading_brake` — at least 10 decisions in the last `activity_window_s` →
   `cooldown_s` ×1.5 (≤ 3600) and `entry_threshold` +0.05 (≤ 0.9).

The `StrategyConfig`/`DetectorConfig` objects are mutated in place — they are the very
objects the aggregator, detectors and execution service hold and read on every use. A
field already at its floor/cap is left alone and not logged; every actual change is
written to `tuning_log` and logged. The tuner never sees, let alone changes, `RiskLimits`.

After every tick (and when `run()` starts) the current effective values are written as
JSON to kv `tuning_effective`, so `ai-trader status` in another process can show them.
"""

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from ai_trader.models import TuningChange
from ai_trader.settings import DetectorConfig, StrategyConfig
from ai_trader.storage.db import Store

log = logging.getLogger(__name__)

EFFECTIVE_KV_KEY = "tuning_effective"

# activity_floor
MIN_SIGNALS = 3
LIQ_FACTOR, LIQ_FLOOR = Decimal("0.7"), Decimal(5000)
NEWS_STEP, NEWS_FLOOR = 0.05, 0.3
FUNDING_FACTOR, FUNDING_FLOOR = Decimal("0.8"), Decimal("0.05")
ENTRY_RELAX_STEP, ENTRY_FLOOR = 0.05, 0.3
# detector_quality
QUALITY_HORIZON_S, QUALITY_MIN_N = 3600, 20
BAD_HIT_RATE, GOOD_HIT_RATE = 0.40, 0.55
WEIGHT_PENALTY, WEIGHT_BONUS, WEIGHT_CAP = 0.25, 0.1, 1.5
# loss_brake
DAILY_PNL_PCT = Decimal("0.02")
NOTIONAL_CUT, NOTIONAL_FLOOR = Decimal("0.5"), Decimal(20)
NOTIONAL_RECOVER, NOTIONAL_DEFAULT = Decimal("1.25"), Decimal(100)
ENTRY_BRAKE_STEP, ENTRY_CAP = 0.1, 0.9
# overtrading_brake
MAX_DECISIONS = 10
COOLDOWN_FACTOR, COOLDOWN_CAP = 1.5, 3600
ENTRY_OVERTRADE_STEP = 0.05

_LIQ_Q, _FUNDING_Q, _NOTIONAL_Q = Decimal(1), Decimal("0.0001"), Decimal("0.01")
_FLOAT_DIGITS = 6


def _dec(value: Decimal, exp: Decimal) -> Decimal:
    """Quantize to `exp`, then drop trailing fractional zeros (35000.0 -> 35000, 0.2400 -> 0.24)."""
    text = format(value.quantize(exp), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return Decimal(text)


def _flt(value: float) -> float:
    return round(value, _FLOAT_DIGITS)


class AutoTuner:
    def __init__(
        self,
        store: Store,
        strategy_cfg: StrategyConfig,
        detector_cfg: DetectorConfig,
        *,
        interval_s: int = 1800,
        activity_window_s: int = 7200,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._store = store
        self.strategy_cfg = strategy_cfg
        self.detector_cfg = detector_cfg
        self._interval_s = interval_s
        self._activity_window_s = activity_window_s
        self._clock = clock
        self._stop_event = asyncio.Event()

    # ---- rules ------------------------------------------------------------

    async def tick(self) -> list[TuningChange]:
        """Evaluate every rule once; returns the changes made (also persisted and logged)."""
        now = datetime.fromtimestamp(self._clock(), UTC)
        since = now - timedelta(seconds=self._activity_window_s)
        n_signals = await self._store.count_signals_since(since)
        n_decisions = await self._store.count_decisions_since(since)

        changes: list[TuningChange] = []
        changes += self._activity_floor(now, n_signals, n_decisions)
        changes += self._detector_quality(now, await self._store.effectiveness())
        changes += await self._loss_brake(now)
        changes += self._overtrading_brake(now, n_decisions)

        for c in changes:
            await self._store.insert_tuning_change(c)
            log.info("autotune %s: %s %s -> %s (%s)", c.rule, c.field, c.old, c.new, c.reason)
        await self.publish_effective()
        return changes

    def _activity_floor(self, now: datetime, n_signals: int, n_decisions: int) -> list[TuningChange]:
        if not (n_signals < MIN_SIGNALS and n_decisions == 0):
            return []
        rule = "activity_floor"
        reason = (
            f"signals={n_signals}<{MIN_SIGNALS} and decisions={n_decisions}==0 "
            f"in last {self._activity_window_s}s"
        )
        d, s = self.detector_cfg, self.strategy_cfg
        out: list[TuningChange] = []
        self._set(out, now, rule, reason, d, "detectors", "liquidation_notional_threshold_usdt",
                  max(LIQ_FLOOR, _dec(d.liquidation_notional_threshold_usdt * LIQ_FACTOR, _LIQ_Q)))
        self._set(out, now, rule, reason, d, "detectors", "news_min_confidence",
                  max(NEWS_FLOOR, _flt(d.news_min_confidence - NEWS_STEP)))
        self._set(out, now, rule, reason, d, "detectors", "funding_annualized_threshold",
                  max(FUNDING_FLOOR, _dec(d.funding_annualized_threshold * FUNDING_FACTOR, _FUNDING_Q)))
        self._set(out, now, rule, reason, s, "strategy", "entry_threshold",
                  max(ENTRY_FLOOR, _flt(s.entry_threshold - ENTRY_RELAX_STEP)))
        return out

    def _detector_quality(self, now: datetime, rows) -> list[TuningChange]:
        weights = self.strategy_cfg.detector_weights  # mutated in place: same dict everyone reads
        out: list[TuningChange] = []
        for row in rows:
            if row.horizon_s != QUALITY_HORIZON_S or row.n < QUALITY_MIN_N or row.detector not in weights:
                continue
            old = weights[row.detector]
            if row.hit_rate < BAD_HIT_RATE and row.mean_ret < 0:
                new = max(0.0, _flt(old - WEIGHT_PENALTY))
            elif row.hit_rate >= GOOD_HIT_RATE and row.mean_ret > 0:
                new = min(WEIGHT_CAP, _flt(old + WEIGHT_BONUS))
            else:
                continue
            if new == old:
                continue
            weights[row.detector] = new
            reason = (
                f"{row.detector} {row.horizon_s}s: n={row.n} hit_rate={row.hit_rate:.3f} "
                f"mean_ret={row.mean_ret:.6f}"
            )
            out.append(self._change(now, "detector_quality", f"strategy.detector_weights.{row.detector}",
                                    old, new, reason))
        return out

    async def _loss_brake(self, now: datetime) -> list[TuningChange]:
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        raw = await self._store.get_kv(f"day_start_equity:{day_start.date().isoformat()}")
        if raw is None:
            return []
        start_equity = Decimal(raw)
        pnl = await self._store.realized_pnl_since(day_start)
        limit = DAILY_PNL_PCT * start_equity
        rule = "loss_brake"
        s = self.strategy_cfg
        out: list[TuningChange] = []
        if pnl <= -limit:
            reason = f"realized_pnl_today={pnl} <= -2% of day_start_equity={start_equity}"
            self._set(out, now, rule, reason, s, "strategy", "base_notional_usdt",
                      max(NOTIONAL_FLOOR, _dec(s.base_notional_usdt * NOTIONAL_CUT, _NOTIONAL_Q)))
            self._set(out, now, rule, reason, s, "strategy", "entry_threshold",
                      min(ENTRY_CAP, _flt(s.entry_threshold + ENTRY_BRAKE_STEP)))
        elif pnl >= limit and s.base_notional_usdt < NOTIONAL_DEFAULT:
            reason = f"realized_pnl_today={pnl} >= +2% of day_start_equity={start_equity}"
            self._set(out, now, rule, reason, s, "strategy", "base_notional_usdt",
                      min(NOTIONAL_DEFAULT, _dec(s.base_notional_usdt * NOTIONAL_RECOVER, _NOTIONAL_Q)))
        return out

    def _overtrading_brake(self, now: datetime, n_decisions: int) -> list[TuningChange]:
        if n_decisions < MAX_DECISIONS:
            return []
        rule = "overtrading_brake"
        reason = f"decisions={n_decisions}>={MAX_DECISIONS} in last {self._activity_window_s}s"
        s = self.strategy_cfg
        out: list[TuningChange] = []
        self._set(out, now, rule, reason, s, "strategy", "cooldown_s",
                  min(COOLDOWN_CAP, int(s.cooldown_s * COOLDOWN_FACTOR)))
        self._set(out, now, rule, reason, s, "strategy", "entry_threshold",
                  min(ENTRY_CAP, _flt(s.entry_threshold + ENTRY_OVERTRADE_STEP)))
        return out

    # ---- helpers ----------------------------------------------------------

    def _set(
        self,
        out: list[TuningChange],
        now: datetime,
        rule: str,
        reason: str,
        cfg: StrategyConfig | DetectorConfig,
        prefix: str,
        name: str,
        new: Any,
    ) -> None:
        old = getattr(cfg, name)
        if new == old:
            return
        setattr(cfg, name, new)
        out.append(self._change(now, rule, f"{prefix}.{name}", old, new, reason))

    @staticmethod
    def _change(now: datetime, rule: str, field: str, old: Any, new: Any, reason: str) -> TuningChange:
        return TuningChange(ts=now, rule=rule, field=field, old=str(old), new=str(new), reason=reason)

    def effective(self) -> dict[str, Any]:
        """The parameters this tuner manages, as currently in effect (JSON-ready)."""
        s, d = self.strategy_cfg, self.detector_cfg
        return {
            "ts": datetime.fromtimestamp(self._clock(), UTC).isoformat(),
            "strategy": {
                "entry_threshold": s.entry_threshold,
                "base_notional_usdt": str(s.base_notional_usdt),
                "cooldown_s": s.cooldown_s,
                "detector_weights": dict(s.detector_weights),
            },
            "detectors": {
                "funding_annualized_threshold": str(d.funding_annualized_threshold),
                "liquidation_notional_threshold_usdt": str(d.liquidation_notional_threshold_usdt),
                "news_min_confidence": d.news_min_confidence,
            },
        }

    async def publish_effective(self) -> None:
        await self._store.set_kv(EFFECTIVE_KV_KEY, json.dumps(self.effective()))

    # ---- lifecycle --------------------------------------------------------

    async def run(self) -> None:
        try:
            await self.publish_effective()
        except Exception:
            log.exception("autotune: publishing effective parameters failed")
        while not self._stop_event.is_set():
            try:
                await self.tick()
            except Exception:
                log.exception("autotune tick failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval_s)

    async def stop(self) -> None:
        self._stop_event.set()
