"""Component wiring and the supervised application runtime (design 5.11).

`create_components` builds every component with its real constructor so tests can inject
fakes (`rest`, `ws_factory`, `http`, `store`). `App.run()` opens the store, starts the bus,
broker, aggregator and execution service, then runs every long-lived component
(including the AutoTuner) under a supervisor in one `asyncio.TaskGroup`: a component that
raises is logged and restarted with backoff, so one crashing component never takes the
process down. `App.stop()` stops everything in reverse order and is idempotent.

The supervised `control` loop (every `control_interval_s`, default 15 s) lets other
processes steer the daemon through the kv table: kv `kill_switch == "1"` (set by
`ai-trader kill`) runs the in-process `KillSwitch.trigger` once per activation, so the
running broker (paper or live) is flattened; kv `stop_requested == "1"` (set by
`ai-trader stop`) resets the flag to "0" and stops the app. A stale `stop_requested`
left from before start-up is cleared when the app starts.
"""

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse

import httpx

from ai_trader.analysis.detectors.base import DetectorRunner
from ai_trader.analysis.detectors.funding_extreme import FundingExtremeDetector
from ai_trader.analysis.detectors.liquidation_burst import LiquidationBurstDetector
from ai_trader.analysis.detectors.news_sentiment import NewsSentimentDetector
from ai_trader.analysis.forward_returns import ForwardReturnTracker
from ai_trader.analysis.sentiment.deepseek import DeepSeekClassifier
from ai_trader.analysis.sentiment.keyword import KeywordClassifier
from ai_trader.bus import EventBus
from ai_trader.data.market_feed import MarketFeed, MarkPriceSampler, StalenessWatchdog
from ai_trader.data.market_state import MarketState
from ai_trader.data.news.base import DailyBudget
from ai_trader.data.news.poller import NewsPoller
from ai_trader.data.news.rss import RssSource
from ai_trader.data.news.x_api import XSearchSource
from ai_trader.exchange.binance.rest import BinanceFuturesRest
from ai_trader.execution.binance import BinanceFuturesBroker
from ai_trader.execution.paper import PaperBroker
from ai_trader.execution.service import ExecutionService
from ai_trader.risk.engine import RiskEngine
from ai_trader.risk.kill_switch import KillSwitch
from ai_trader.settings import Settings
from ai_trader.storage.db import Store
from ai_trader.strategy.aggregator import SignalAggregator
from ai_trader.strategy.autotune import AutoTuner

log = logging.getLogger(__name__)

PAPER_INITIAL_BALANCE = Decimal(10000)
DEFAULT_BACKOFF_S: tuple[float, ...] = (1, 2, 5, 10, 30)
HEALTH_INTERVAL_S = 60.0
STABLE_RUN_S = 60.0  # a run longer than this resets the backoff schedule
STOP_GRACE_S = 15.0
CONTROL_INTERVAL_S = 15.0
KILL_KV_KEY = "kill_switch"
STOP_KV_KEY = "stop_requested"


@dataclass
class Components:
    settings: Settings
    bus: EventBus
    store: Store
    state: MarketState
    rest: Any
    http: httpx.AsyncClient
    broker: PaperBroker | BinanceFuturesBroker
    feed: MarketFeed
    watchdog: StalenessWatchdog
    sampler: MarkPriceSampler
    detectors: list
    runner: DetectorRunner
    poller: NewsPoller
    aggregator: SignalAggregator
    risk: RiskEngine
    kill_switch: KillSwitch
    execution: ExecutionService
    tracker: ForwardReturnTracker
    tuner: AutoTuner


def _secret(value) -> str | None:
    return value.get_secret_value() if value is not None else None


def _build_classifier(settings: Settings, http: httpx.AsyncClient):
    keyword = KeywordClassifier(settings.symbols)
    llm = settings.llm
    if llm.enabled and llm.provider == "deepseek" and settings.deepseek_api_key:
        return DeepSeekClassifier(
            http,
            settings.deepseek_api_key.get_secret_value(),
            settings.symbols,
            model=llm.model,
            base_url=llm.base_url,
            fallback=keyword,
            budget=DailyBudget(llm.daily_call_budget),
            max_text_chars=llm.max_text_chars,
            timeout_s=llm.timeout_s,
        )
    return keyword


def _build_sources(settings: Settings, http: httpx.AsyncClient) -> list[tuple[Any, int]]:
    news = settings.news
    sources: list[tuple[Any, int]] = [
        (RssSource(f"rss:{urlparse(url).netloc or url}", url, http), news.rss_poll_interval_s)
        for url in news.rss_feeds
    ]
    if news.x_bearer_token:
        x = XSearchSource(
            news.x_bearer_token.get_secret_value(),
            news.x_query,
            http,
            DailyBudget(news.x_daily_read_budget),
            max_results=news.x_max_results,
        )
        sources.append((x, news.x_poll_interval_s))
    return sources


async def create_components(
    settings: Settings,
    *,
    rest=None,
    ws_factory=None,
    http: httpx.AsyncClient | None = None,
    store: Store | None = None,
) -> Components:
    key = _secret(settings.binance_api_key)
    secret = _secret(settings.binance_api_secret)
    if settings.mode == "live" and not (key and secret):
        raise SystemExit("live 模式需要 BINANCE_API_KEY/BINANCE_API_SECRET")
    if settings.leverage > settings.risk.max_leverage:
        raise SystemExit(
            f"LEVERAGE={settings.leverage} exceeds RISK__MAX_LEVERAGE={settings.risk.max_leverage}"
        )

    own_rest, own_http = rest is None, http is None
    rest = rest or BinanceFuturesRest(settings.effective_rest_url, key, secret)
    http = http or httpx.AsyncClient(timeout=30.0, follow_redirects=True)
    try:
        return await _wire(settings, rest, http, ws_factory, store)
    except BaseException:
        # Close only the clients this call created; injected ones belong to the caller.
        if own_rest:
            await rest.aclose()
        if own_http:
            await http.aclose()
        raise


async def _wire(settings: Settings, rest, http: httpx.AsyncClient, ws_factory, store: Store | None) -> Components:
    if settings.mode == "live":
        # Signed requests carry a timestamp checked against recvWindow: align to server time.
        await rest.sync_time()
    exchange_info = await rest.exchange_info()

    bus = EventBus()
    store = store or Store(settings.db_path)
    state = MarketState()

    feed = MarketFeed(bus, state, settings.effective_ws_url, settings.symbols, ws_factory=ws_factory)
    watchdog = StalenessWatchdog(bus, state, settings.symbols, settings.risk.max_data_staleness_s)
    sampler = MarkPriceSampler(bus, store)

    classifier = _build_classifier(settings, http)
    detectors = [
        FundingExtremeDetector(settings.detectors, state),
        LiquidationBurstDetector(settings.detectors, state),
        NewsSentimentDetector(
            classifier, settings.symbols, store, state, settings.detectors, news_cfg=settings.news
        ),
    ]
    runner = DetectorRunner(bus, store, detectors)
    poller = NewsPoller(bus, store, _build_sources(settings, http))

    kill_switch: KillSwitch | None = None

    async def _kill(reason: str) -> None:
        # Only ever called after start-up, by which time `kill_switch` is bound.
        assert kill_switch is not None
        await kill_switch.trigger(reason)

    broker: PaperBroker | BinanceFuturesBroker
    if settings.mode == "paper":
        # `store`: the simulated account survives restarts (kv `paper_state`).
        broker = PaperBroker(state, bus, exchange_info, initial_balance=PAPER_INITIAL_BALANCE, store=store)
    else:
        broker = BinanceFuturesBroker(
            rest, exchange_info, bus, settings.effective_ws_url, ws_factory=ws_factory, kill=_kill
        )
    kill_switch = KillSwitch(store, broker, bus)

    risk = RiskEngine(settings.risk, store, state, settings.symbols)
    aggregator = SignalAggregator(bus, store, state, settings.strategy, positions=broker.positions_snapshot)
    execution = ExecutionService(bus, broker, risk, store, settings, state=state)
    tracker = ForwardReturnTracker(store, state)
    # Same config objects the aggregator/detectors/execution read; RiskLimits is never passed.
    tuner = AutoTuner(store, settings.strategy, settings.detectors)

    return Components(
        settings=settings,
        bus=bus,
        store=store,
        state=state,
        rest=rest,
        http=http,
        broker=broker,
        feed=feed,
        watchdog=watchdog,
        sampler=sampler,
        detectors=detectors,
        runner=runner,
        poller=poller,
        aggregator=aggregator,
        risk=risk,
        kill_switch=kill_switch,
        execution=execution,
        tracker=tracker,
        tuner=tuner,
    )


class App:
    def __init__(
        self,
        components: Components,
        *,
        backoff_s: Sequence[float] = DEFAULT_BACKOFF_S,
        health_interval_s: float = HEALTH_INTERVAL_S,
        stop_grace_s: float = STOP_GRACE_S,
        control_interval_s: float = CONTROL_INTERVAL_S,
    ) -> None:
        if not backoff_s:
            raise ValueError("backoff_s must not be empty")
        self.c = components
        self._backoff_s = tuple(backoff_s)
        self._health_interval_s = health_interval_s
        self._stop_grace_s = stop_grace_s
        self._control_interval_s = control_interval_s
        self._kill_handled = False  # the current kv kill activation was already acted on
        self._stopping = asyncio.Event()
        self._done = asyncio.Event()
        self._run_task: asyncio.Task | None = None
        self._components_stopped = False
        self._torn_down = False

    # ---- lifecycle --------------------------------------------------------

    def _supervised(self) -> list[tuple[str, Callable[[], Awaitable[None]]]]:
        c = self.c
        return [
            ("feed", lambda: c.feed.run()),
            ("watchdog", lambda: c.watchdog.run()),
            ("poller", lambda: c.poller.run()),
            ("execution", lambda: c.execution.run()),
            ("tracker", lambda: c.tracker.run()),
            ("tuner", lambda: c.tuner.run()),
            ("health", self._health_loop),
            ("control", self._control_loop),
        ]

    async def run(self) -> None:
        if self._run_task is not None:
            raise RuntimeError("App.run() may only be called once")
        self._run_task = asyncio.current_task()
        if self._torn_down:  # stop() already ran before run() started
            self._done.set()
            return
        c = self.c
        try:
            await c.store.open()
            if await c.store.get_kv(STOP_KV_KEY) == "1":
                log.warning("clearing a stale %s flag left from before start-up", STOP_KV_KEY)
                await c.store.set_kv(STOP_KV_KEY, "0")
            await c.bus.start()
            await c.broker.start()
            await c.aggregator.start()
            await c.execution.start()
            log.info(
                "ai_trader running: mode=%s symbols=%s endpoint=%s",
                c.settings.mode,
                ",".join(c.settings.symbols),
                c.settings.effective_rest_url,
            )
            if not self._stopping.is_set():
                async with asyncio.TaskGroup() as tg:
                    for name, factory in self._supervised():
                        tg.create_task(self._supervise(name, factory), name=f"supervise-{name}")
        finally:
            await self._teardown()
            self._done.set()

    async def stop(self) -> None:
        self._stopping.set()
        await self._stop_components()
        task = self._run_task
        if task is None:
            await self._teardown()
            return
        if task is asyncio.current_task():
            return
        try:
            await asyncio.wait_for(asyncio.shield(self._done.wait()), timeout=self._stop_grace_s)
        except TimeoutError:
            log.warning("components did not stop within %.0f s; cancelling", self._stop_grace_s)
            task.cancel()
            await self._done.wait()

    async def _stop_components(self) -> None:
        if self._components_stopped:
            return
        self._components_stopped = True
        c = self.c
        for name, comp in (
            ("feed", c.feed),
            ("watchdog", c.watchdog),
            ("poller", c.poller),
            ("execution", c.execution),
            ("tracker", c.tracker),
            ("tuner", c.tuner),
        ):
            try:
                await comp.stop()
            except Exception:
                log.exception("stopping %s failed", name)

    async def _teardown(self) -> None:
        if self._torn_down:
            return
        self._torn_down = True
        self._stopping.set()
        await self._stop_components()
        c = self.c
        for name, close in (
            ("broker", c.broker.stop),
            ("bus", c.bus.stop),
            ("rest", c.rest.aclose),
            ("http", c.http.aclose),
            ("store", c.store.close),
        ):
            try:
                await close()
            except Exception:
                log.exception("closing %s failed", name)
        log.info("ai_trader stopped")

    # ---- supervisor -------------------------------------------------------

    async def _supervise(self, name: str, factory: Callable[[], Awaitable[None]]) -> None:
        failures = 0
        while not self._stopping.is_set():
            started = time.monotonic()
            try:
                await factory()
            except asyncio.CancelledError:
                raise
            except Exception:
                if self._stopping.is_set():
                    log.exception("component %s failed while stopping", name)
                    return
                log.exception("component %s crashed; restarting", name)
            else:
                if self._stopping.is_set():
                    return
                log.warning("component %s returned unexpectedly; restarting", name)
            if time.monotonic() - started > STABLE_RUN_S:
                failures = 0
            delay = self._backoff_s[min(failures, len(self._backoff_s) - 1)]
            failures += 1
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stopping.wait(), timeout=delay)

    # ---- external control (kv flags) ---------------------------------------

    async def _control_loop(self) -> None:
        while not self._stopping.is_set():
            try:
                await self._check_control()
            except Exception:
                log.exception("control check failed")
            if self._stopping.is_set():
                return
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stopping.wait(), timeout=self._control_interval_s)

    async def _check_control(self) -> None:
        c = self.c
        if await c.store.get_kv(KILL_KV_KEY) == "1":
            if not self._kill_handled:
                self._kill_handled = True
                if not c.kill_switch.triggered:
                    log.error("kill flag observed in kv; flattening the in-process broker")
                    await c.kill_switch.trigger("kill flag observed")
        else:
            # Reset (e.g. `ai-trader kill --reset`): a later kill acts again.
            self._kill_handled = False
            c.kill_switch.triggered = False
        if await c.store.get_kv(STOP_KV_KEY) == "1":
            log.warning("stop requested via kv %s; shutting down", STOP_KV_KEY)
            try:
                await c.store.set_kv(STOP_KV_KEY, "0")
            finally:
                # Not `self.stop()`: that waits for run() to finish, and run() is waiting
                # for this very task.
                self._stopping.set()
                await self._stop_components()

    # ---- health -----------------------------------------------------------

    async def _health_loop(self) -> None:
        while not self._stopping.is_set():
            try:
                await self._log_health()
            except Exception:
                log.exception("health check failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stopping.wait(), timeout=self._health_interval_s)

    async def _log_health(self) -> None:
        c = self.c
        ages = []
        for symbol in c.settings.symbols:
            age = c.state.age_s(symbol)
            ages.append(f"{symbol}={'none' if age is None else f'{age:.1f}s'}")
        counts = {t: await c.store.count(t) for t in ("signals", "decisions", "fills", "news", "mark_samples")}
        positions = c.broker.positions_snapshot()
        pos_text = ",".join(f"{s}:{p.side.value}:{p.quantity}" for s, p in positions.items()) or "none"
        kill = "ACTIVE" if await c.kill_switch.is_active() else "off"
        stale_news = sum(getattr(d, "stale_skipped", 0) for d in c.detectors)
        log.info(
            "health: mark_age[%s] counts[%s] positions[%s] kill_switch=%s stale_news_skipped=%d",
            " ".join(ages),
            " ".join(f"{k}={v}" for k, v in counts.items()),
            pos_text,
            kill,
            stale_news,
        )
