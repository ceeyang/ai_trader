"""Command-line entrypoint for ai_trader."""

import asyncio
import time

import typer

from ai_trader import __version__

app = typer.Typer(no_args_is_help=True)


@app.callback()
def main() -> None:
    """ai_trader command-line interface."""


@app.command()
def version() -> None:
    """Print the installed ai_trader version."""
    print(__version__)


async def _probe() -> None:
    from ai_trader.exchange.binance.rest import BinanceFuturesRest
    from ai_trader.settings import Settings

    s = Settings()
    key = s.binance_api_key.get_secret_value() if s.binance_api_key else None
    secret = s.binance_api_secret.get_secret_value() if s.binance_api_secret else None
    rest = BinanceFuturesRest(s.effective_rest_url, key, secret)
    try:
        print(f"endpoint: {s.effective_rest_url}")
        t0 = time.perf_counter()
        await rest.ping()
        print(f"ping: {(time.perf_counter() - t0) * 1000:.0f} ms")
        offset = await rest.sync_time()
        server = int(time.time() * 1000) + offset
        print(f"server_time: {server} (local offset {offset:+d} ms)")
        info = await rest.exchange_info()
        print(f"exchange_info: {len(info.symbols)} trading perpetuals")
        for symbol in s.symbols:
            mp = await rest.premium_index(symbol)
            annualized = mp.funding_rate * 3 * 365
            print(
                f"{symbol}: mark={mp.mark_price} funding={mp.funding_rate} "
                f"(annualized {annualized:.2%}) next_funding={mp.next_funding_time.isoformat()}"
            )
        if key and secret:
            acc = await rest.account()
            print(f"total_wallet_balance: {acc.total_wallet_balance} USDT")
        else:
            print("account: skipped (no API key configured)")
    finally:
        await rest.aclose()


@app.command()
def probe() -> None:
    """Check connectivity to the configured Binance futures endpoint."""
    from ai_trader.exchange.binance.errors import BinanceAPIError, BinanceError

    try:
        asyncio.run(_probe())
    except BinanceAPIError as exc:
        print(f"probe failed: {type(exc).__name__} code={exc.code} msg={exc.msg}")
        raise typer.Exit(1) from None
    except BinanceError as exc:
        print(f"probe failed: {type(exc).__name__}: {exc}")
        raise typer.Exit(1) from None


async def _classify(text: str) -> None:
    import json

    import httpx

    from ai_trader.analysis.sentiment.deepseek import DeepSeekClassifier
    from ai_trader.analysis.sentiment.keyword import KeywordClassifier
    from ai_trader.data.news.base import DailyBudget
    from ai_trader.models import NewsItem, new_id, utc_now
    from ai_trader.settings import Settings

    s = Settings()
    item = NewsItem(
        id=new_id(),
        source="cli",
        author=None,
        title=text[:120],
        text=text,
        url=None,
        published_at=utc_now(),
        fetched_at=utc_now(),
    )
    keyword = KeywordClassifier(s.symbols)
    async with httpx.AsyncClient() as http:
        if s.llm.enabled and s.llm.provider == "deepseek" and s.deepseek_api_key:
            classifier = DeepSeekClassifier(
                http,
                s.deepseek_api_key.get_secret_value(),
                s.symbols,
                model=s.llm.model,
                base_url=s.llm.base_url,
                fallback=keyword,
                budget=DailyBudget(s.llm.daily_call_budget),
                max_text_chars=s.llm.max_text_chars,
                timeout_s=s.llm.timeout_s,
            )
            sentiment = await classifier.classify(item)
        else:
            sentiment = await keyword.classify(item)
    print(json.dumps(sentiment.model_dump(mode="json"), ensure_ascii=False, indent=2))


@app.command()
def classify(text: str) -> None:
    """Classify the sentiment of TEXT as if it were a news item."""
    asyncio.run(_classify(text))


async def _run(settings) -> None:
    import signal

    from ai_trader.app import App, create_components

    components = await create_components(settings)
    application = App(components)
    loop = asyncio.get_running_loop()
    stop_tasks: set[asyncio.Task] = set()

    def _request_stop() -> None:
        task = loop.create_task(application.stop())
        stop_tasks.add(task)
        task.add_done_callback(stop_tasks.discard)

    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _request_stop)
    except NotImplementedError:
        # Windows: no loop signal handlers. Ctrl+C cancels the main task instead, and
        # `App.run()` tears everything down in its `finally`; `run` catches the
        # resulting KeyboardInterrupt. Ctrl+Break (what process managers send) is routed
        # to a graceful stop as well.
        if hasattr(signal, "SIGBREAK"):
            signal.signal(signal.SIGBREAK, lambda *_: loop.call_soon_threadsafe(_request_stop))
    try:
        await application.run()
    finally:
        await application.stop()


@app.command()
def run(
    mode: str | None = typer.Option(None, "--mode", help="paper | live (overrides MODE)"),
    confirm_mainnet: bool = typer.Option(False, "--confirm-mainnet", help="required whenever the REST/WS endpoints are not the Binance futures testnet"),
) -> None:
    """Run the trading system until interrupted."""
    from ai_trader.logging_setup import configure_logging
    from ai_trader.settings import Settings

    settings = Settings()
    if mode is not None:
        if mode not in ("paper", "live"):
            print(f"invalid --mode {mode!r}; expected paper or live")
            raise typer.Exit(2)
        settings = settings.model_copy(update={"mode": mode})
    configure_logging(settings.log_level, settings.log_json)
    if not settings.targets_testnet and not confirm_mainnet:
        print(
            f"endpoints {settings.effective_rest_url} / {settings.effective_ws_url} are not the Binance "
            "futures testnet (MAINNET means real funds). "
            "Re-run with --confirm-mainnet if that is really intended."
        )
        raise typer.Exit(2)
    try:
        asyncio.run(_run(settings))
    except KeyboardInterrupt:
        print("interrupted; shut down")


def _today_utc_midnight():
    from datetime import UTC, datetime

    return datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


async def _kill(reset: bool = False) -> None:
    import httpx

    from ai_trader.bus import EventBus
    from ai_trader.exchange.binance.errors import BinanceError
    from ai_trader.exchange.binance.rest import BinanceFuturesRest
    from ai_trader.execution.binance import BinanceFuturesBroker
    from ai_trader.risk.kill_switch import KillSwitch
    from ai_trader.settings import Settings
    from ai_trader.storage.db import Store

    s = Settings()
    store = Store(s.db_path)
    await store.open()
    try:
        if reset:
            await KillSwitch.reset_flag(store)
            state = "ACTIVE" if await store.get_kv("kill_switch") == "1" else "inactive"
            print(f"kill switch reset: {state} (new entries are allowed again)")
            return
        # Persist the flag first: whatever happens to the flatten below, the running
        # process rejects every new entry from now on.
        await store.set_kv("kill_switch", "1")
        if s.mode == "paper":
            print(
                "kill switch set (paper mode): the running process rejects new entries from now on "
                "and flattens its paper positions when it observes the flag (within ~15 s)."
            )
            return
        print("kill switch flag set; flattening live positions...")
        key = s.binance_api_key.get_secret_value() if s.binance_api_key else None
        secret = s.binance_api_secret.get_secret_value() if s.binance_api_secret else None
        if not (key and secret):
            print("flatten NOT run: no BINANCE_API_KEY/BINANCE_API_SECRET configured")
            raise typer.Exit(1)
        rest = BinanceFuturesRest(s.effective_rest_url, key, secret)
        try:
            await rest.sync_time()
            info = await rest.exchange_info()
            bus = EventBus()
            broker = BinanceFuturesBroker(rest, info, bus, s.effective_ws_url)
            await broker.refresh_positions()
        except (BinanceError, httpx.HTTPError) as exc:
            print(f"flatten NOT run: REST setup failed ({type(exc).__name__}); positions may still be open")
            raise typer.Exit(1) from None
        else:
            # KillSwitch.trigger tolerates per-symbol failures and records them.
            ks = KillSwitch(store, broker, bus)
            await ks.trigger("manual kill via CLI")
            if ks.last_errors:
                print("kill switch triggered, but the flatten sweep had failures:")
                for err in ks.last_errors:
                    print(f"  {err}")
                print("positions or orders may still be open; check `ai-trader status`")
                raise typer.Exit(1)
            print("kill switch triggered: flatten sweep ran over all positions and open orders")
        finally:
            await rest.aclose()
    finally:
        await store.close()


@app.command()
def kill(
    reset: bool = typer.Option(False, "--reset", help="clear the kill switch (kv kill_switch=0) instead of setting it"),
) -> None:
    """Set the persistent kill switch (live mode: also flatten positions and cancel orders)."""
    asyncio.run(_kill(reset))


async def _stop() -> None:
    from ai_trader.settings import Settings
    from ai_trader.storage.db import Store

    s = Settings()
    store = Store(s.db_path)
    await store.open()
    try:
        await store.set_kv("stop_requested", "1")
    finally:
        await store.close()
    print("stop requested: the running daemon will shut down gracefully within ~15 s")


@app.command()
def stop() -> None:
    """Ask the running daemon to shut down gracefully (kv stop_requested=1)."""
    asyncio.run(_stop())


# What a malformed kv JSON blob can raise while being read (JSONDecodeError is a ValueError,
# decimal.InvalidOperation an ArithmeticError).
_UNREADABLE = (ValueError, KeyError, TypeError, AttributeError, IndexError, ArithmeticError)


def _print_tuning_params(s, effective_json: str | None) -> None:
    """Print the auto-tuned parameters: the running process's values from kv
    `tuning_effective` when present, else this process's configured defaults."""
    try:
        lines = _tuning_param_lines(s, effective_json)
    except _UNREADABLE as exc:  # a bad kv value must not break `status`
        lines = [f"tuned parameters - unreadable kv `tuning_effective` ({type(exc).__name__})"]
    for line in lines:
        print(line)


def _tuning_param_lines(s, effective_json: str | None) -> list[str]:
    import json

    if effective_json is not None:
        eff = json.loads(effective_json)
        head = f"tuned parameters - effective (from running process), as of {eff.get('ts', '?')}:"
        strat, det = eff["strategy"], eff["detectors"]
    else:
        head = "tuned parameters - configured defaults (no running process has published values yet):"
        strat = {
            "entry_threshold": s.strategy.entry_threshold,
            "base_notional_usdt": str(s.strategy.base_notional_usdt),
            "cooldown_s": s.strategy.cooldown_s,
            "detector_weights": s.strategy.detector_weights,
        }
        det = {
            "funding_annualized_threshold": str(s.detectors.funding_annualized_threshold),
            "liquidation_notional_threshold_usdt": str(s.detectors.liquidation_notional_threshold_usdt),
            "news_min_confidence": s.detectors.news_min_confidence,
        }
    weights = " ".join(f"{k}={v:g}" for k, v in sorted(strat["detector_weights"].items()))
    return [
        head,
        (
            f"  entry_threshold={strat['entry_threshold']:g}  base_notional_usdt={strat['base_notional_usdt']}  "
            f"cooldown_s={strat['cooldown_s']}"
        ),
        f"  detector_weights: {weights}",
        (
            f"  funding_annualized_threshold={det['funding_annualized_threshold']}  "
            f"liquidation_notional_threshold_usdt={det['liquidation_notional_threshold_usdt']}  "
            f"news_min_confidence={det['news_min_confidence']:g}"
        ),
    ]


def _print_paper_state(raw: str | None) -> None:
    """Print the paper account as last persisted by the running process (kv `paper_state`)."""
    if raw is None:
        print("positions: no persisted paper account yet (starts when `ai-trader run --mode paper` trades)")
        return
    try:
        lines = _paper_state_lines(raw)
    except _UNREADABLE as exc:  # a bad kv value must not break `status`
        lines = [f"paper account: unreadable kv `paper_state` ({type(exc).__name__})"]
    for line in lines:
        print(line)


def _paper_state_lines(raw: str) -> list[str]:
    import json
    from decimal import Decimal

    snap = json.loads(raw)
    lines = [f"paper account (persisted): wallet={snap['wallet_balance']} realized_pnl={snap['realized_pnl']} USDT"]
    positions = snap["positions"]
    lines.append("positions:" + ("" if positions else " (none)"))
    for symbol, p in sorted(positions.items()):
        qty = Decimal(p["qty"])
        side = "LONG" if qty > 0 else "SHORT"
        lines.append(f"  {symbol:<10} {side:<5} qty={abs(qty)} entry={p['entry_price']}")
    pending = snap["pending"]
    lines.append("open orders:" + ("" if pending else " (none)"))
    for item in pending:
        req = item["request"]
        lines.append(
            f"  {req['symbol']:<10} {req['side']:<4} {req['type']:<20} stop={req['stop_price']} "
            f"{req['client_order_id']}"
        )
    return lines


async def _status() -> None:
    from ai_trader.exchange.binance.errors import BinanceError
    from ai_trader.exchange.binance.rest import BinanceFuturesRest
    from ai_trader.settings import Settings
    from ai_trader.storage.db import Store

    s = Settings()
    store = Store(s.db_path)
    await store.open()
    try:
        kill_active = await store.get_kv("kill_switch") == "1"
        print(f"mode: {s.mode}  endpoint: {s.effective_rest_url}  db: {s.db_path}")
        print(f"kill switch: {'ACTIVE' if kill_active else 'inactive'}")
        pnl = await store.realized_pnl_since(_today_utc_midnight())
        print(f"realized PnL today (UTC): {pnl} USDT")
        counts = [f"{t}={await store.count(t)}" for t in ("signals", "decisions", "orders", "fills", "news")]
        print("counts: " + " ".join(counts))
        _print_tuning_params(s, await store.get_kv("tuning_effective"))
        signals = await store.recent_signals(10)
        print("last signals (UTC):")
        if not signals:
            print("  (none)")
        for sig in signals:
            print(
                f"  {sig.created_at.strftime('%Y-%m-%d %H:%M:%S')}  {sig.detector:<18} {sig.symbol:<10} "
                f"{sig.direction.value:<8} {sig.strength:.2f}"
            )
        paper_state = await store.get_kv("paper_state") if s.mode == "paper" else None
    finally:
        await store.close()

    if s.mode == "paper":
        _print_paper_state(paper_state)
        return
    key = s.binance_api_key.get_secret_value() if s.binance_api_key else None
    secret = s.binance_api_secret.get_secret_value() if s.binance_api_secret else None
    if not (key and secret):
        print("positions: skipped (no API key configured)")
        return
    rest = BinanceFuturesRest(s.effective_rest_url, key, secret)
    try:
        positions = [p for p in await rest.position_risk() if p.quantity > 0]
        print("positions:" + ("" if positions else " (none)"))
        for p in positions:
            print(
                f"  {p.symbol:<10} {p.side.value:<5} qty={p.quantity} entry={p.entry_price} "
                f"mark={p.mark_price} uPnL={p.unrealized_pnl}"
            )
        orders = await rest.open_orders()
        print("open orders:" + ("" if orders else " (none)"))
        for o in orders:
            stop = f" stop={o.stop_price}" if o.stop_price is not None else ""
            print(
                f"  {o.symbol:<10} {o.side.value:<4} {o.type.value:<20} qty={o.orig_qty}{stop} "
                f"{o.status.value} {o.client_order_id}"
            )
    except BinanceError as exc:
        print(f"positions/orders: REST query failed: {type(exc).__name__}")
    finally:
        await rest.aclose()


@app.command()
def status() -> None:
    """Show kill-switch state, today's PnL, counts, recent signals and (live) positions."""
    asyncio.run(_status())


async def _signals() -> None:
    from ai_trader.settings import Settings
    from ai_trader.storage.db import Store

    s = Settings()
    store = Store(s.db_path)
    await store.open()
    try:
        rows = await store.effectiveness()
    finally:
        await store.close()
    if not rows:
        print("no data yet")
        return
    print(f"{'detector':<20} {'horizon_s':>9} {'n':>6} {'mean_ret':>10} {'hit_rate':>9}")
    for r in sorted(rows, key=lambda r: (r.detector, r.horizon_s)):
        print(f"{r.detector:<20} {r.horizon_s:>9} {r.n:>6} {r.mean_ret:>10.3%} {r.hit_rate:>9.1%}")


@app.command()
def signals() -> None:
    """Print signal effectiveness (forward returns per detector and horizon)."""
    asyncio.run(_signals())


async def _tuning() -> None:
    from ai_trader.settings import Settings
    from ai_trader.storage.db import Store

    s = Settings()
    store = Store(s.db_path)
    await store.open()
    try:
        rows = await store.tuning_log(50)
    finally:
        await store.close()
    if not rows:
        print("no tuning changes yet")
        return
    print(f"{'ts (UTC)':<19}  {'rule':<17} {'field':<45} {'old':>10} {'new':>10}  reason")
    for r in rows:
        print(
            f"{r.ts.strftime('%Y-%m-%d %H:%M:%S'):<19}  {r.rule:<17} {r.field:<45} "
            f"{r.old:>10} {r.new:>10}  {r.reason}"
        )


@app.command()
def tuning() -> None:
    """Print the last 50 AutoTuner parameter changes (newest first)."""
    asyncio.run(_tuning())
