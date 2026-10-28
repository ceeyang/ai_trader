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
