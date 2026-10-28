"""RiskEngine: hard pre-trade limits, evaluated fresh on every call (design 5.8).

Checks run in this exact order and stop at the first failure: kill switch -> trading
enabled -> symbol allow-list -> market data freshness. Those first three always apply,
regardless of intent. Data freshness only gates OPEN: closing a position is a
risk-*reducing* action, so it must not be blocked by a stale or missing market feed — a
CLOSE decision that clears kill switch/trading-enabled/symbol-allowed is approved
outright. An OPEN decision that also clears the freshness check continues through
notional-cap, total-exposure, open-position-count, daily-loss and consecutive-loss
checks, in that order.

`limits` fields are read fresh on every call (never cached), since other config is
mutated at runtime by the AutoTuner (`RiskLimits` itself never is, but this engine does
not assume that). Every verdict — approved or not — is persisted via
`store.insert_risk_verdict` before `evaluate` returns.

`clock()` is read once per `evaluate` call and used to derive both the UTC day key and
the day-start window, so a single call can't straddle two different "now"s. The day's
starting equity (`day_start_equity:<day>`) is written, if missing, at the very start of
every call — regardless of intent or outcome — so it reflects the account's balance at
the first evaluation of the day, not just the first OPEN that happens to reach the
daily-loss check.
"""

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

from ai_trader.data.market_state import MarketState
from ai_trader.models import AccountState, Decision, Intent, RiskVerdict
from ai_trader.settings import RiskLimits
from ai_trader.storage.db import Store

log = logging.getLogger(__name__)


class RiskEngine:
    """Hard, non-adaptive pre-trade risk limits (design 5.8)."""

    def __init__(
        self,
        limits: RiskLimits,
        store: Store,
        state: MarketState,
        allowed_symbols: list[str],
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._limits = limits
        self._store = store
        self._state = state
        self._allowed_symbols = allowed_symbols
        self._clock = clock

    async def evaluate(self, d: Decision, account: AccountState) -> RiskVerdict:
        verdict = await self._evaluate(d, account)
        await self._store.insert_risk_verdict(d.id, verdict)
        return verdict

    async def _evaluate(self, d: Decision, account: AccountState) -> RiskVerdict:
        limits = self._limits  # read fresh at call time, never cached
        now = self._clock()
        day_start = datetime.fromtimestamp(now, UTC).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        # Capture the day's starting equity on the first evaluation of the day,
        # regardless of what this particular decision's outcome turns out to be.
        start = await self._day_start_equity(day_start, account)

        if await self._store.get_kv("kill_switch") == "1":
            return self._rejected(d, "kill_switch")
        if not limits.trading_enabled:
            return self._rejected(d, "trading_disabled")
        if d.symbol not in self._allowed_symbols:
            return self._rejected(d, "symbol_not_allowed")

        if d.intent != Intent.OPEN:
            return RiskVerdict(approved=True)

        age = self._state.age_s(d.symbol)
        if age is None or age > limits.max_data_staleness_s:
            return self._rejected(d, "data_stale")

        notional = d.notional_usdt
        adjusted_notional: Decimal | None = None
        if notional > limits.max_order_notional_usdt:
            adjusted_notional = limits.max_order_notional_usdt
            notional = adjusted_notional

        exposure = sum((p.notional for p in account.open_positions()), Decimal(0)) + notional
        if exposure > limits.max_total_exposure_usdt:
            return self._rejected(d, "max_total_exposure", adjusted_notional)

        if len(account.open_positions()) >= limits.max_open_positions:
            return self._rejected(d, "max_open_positions", adjusted_notional)

        pnl = await self._store.realized_pnl_since(day_start)
        threshold = -(limits.max_daily_loss_pct / Decimal(100)) * start
        if pnl <= threshold:
            return self._rejected(d, "daily_loss_limit", adjusted_notional)

        if await self._store.consecutive_losses() >= limits.max_consecutive_losses:
            return self._rejected(d, "consecutive_losses", adjusted_notional)

        return RiskVerdict(approved=True, adjusted_notional=adjusted_notional)

    async def _day_start_equity(self, day_start: datetime, account: AccountState) -> Decimal:
        key = f"day_start_equity:{day_start.date().isoformat()}"
        existing = await self._store.get_kv(key)
        if existing is None:
            existing = str(account.total_wallet_balance)
            await self._store.set_kv(key, existing)
        return Decimal(existing)

    def _rejected(
        self, d: Decision, reason: str, adjusted_notional: Decimal | None = None
    ) -> RiskVerdict:
        log.warning("risk rejected decision %s: reason=%s symbol=%s", d.id, reason, d.symbol)
        return RiskVerdict(approved=False, reason=reason, adjusted_notional=adjusted_notional)
