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
        server = await rest.server_time()
        rest.time_offset_ms = server - int(time.time() * 1000)
        print(f"server_time: {server} (local offset {rest.time_offset_ms:+d} ms)")
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
