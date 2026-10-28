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
    confirm_mainnet: bool = typer.Option(False, "--confirm-mainnet", help="required when BINANCE_TESTNET=false"),
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
    if not settings.binance_testnet and not confirm_mainnet:
        print(
            "BINANCE_TESTNET=false points at Binance MAINNET (real funds). "
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


async def _kill() -> None:
    from ai_trader.bus import EventBus
    from ai_trader.exchange.binance.rest import BinanceFuturesRest
    from ai_trader.execution.binance import BinanceFuturesBroker
    from ai_trader.risk.kill_switch import KillSwitch
    from ai_trader.settings import Settings
    from ai_trader.storage.db import Store

    s = Settings()
    store = Store(s.db_path)
    await store.open()
    try:
        if s.mode == "paper":
            await store.set_kv("kill_switch", "1")
            print(
                "kill switch set (paper mode): the running process rejects new entries from now on; "
                "paper positions live in that process and close via their stops or max-hold."
            )
            return
        key = s.binance_api_key.get_secret_value() if s.binance_api_key else None
        secret = s.binance_api_secret.get_secret_value() if s.binance_api_secret else None
        if not (key and secret):
            await store.set_kv("kill_switch", "1")
            print("kill switch set, but no BINANCE_API_KEY/BINANCE_API_SECRET: cannot flatten positions")
            raise typer.Exit(1)
        rest = BinanceFuturesRest(s.effective_rest_url, key, secret)
        try:
            info = await rest.exchange_info()
            bus = EventBus()
            broker = BinanceFuturesBroker(rest, info, bus, s.effective_ws_url)
            await broker.refresh_positions()
            await KillSwitch(store, broker, bus).trigger("manual kill via CLI")
            print("kill switch triggered: positions flattened and open orders cancelled (see log for failures)")
        finally:
            await rest.aclose()
    finally:
        await store.close()


@app.command()
def kill() -> None:
    """Set the persistent kill switch (live mode: also flatten positions and cancel orders)."""
    asyncio.run(_kill())


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
        signals = await store.recent_signals(10)
        print("last signals (UTC):")
        if not signals:
            print("  (none)")
        for sig in signals:
            print(
                f"  {sig.created_at.strftime('%Y-%m-%d %H:%M:%S')}  {sig.detector:<18} {sig.symbol:<10} "
                f"{sig.direction.value:<8} {sig.strength:.2f}"
            )
    finally:
        await store.close()

    if s.mode == "paper":
        print("positions: paper positions live in the running `ai-trader run` process (see its health log)")
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
