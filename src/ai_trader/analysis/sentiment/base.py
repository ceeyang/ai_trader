"""Sentiment classifier protocol and symbol canonicalization shared by all classifiers."""

from collections.abc import Iterable, Sequence
from typing import Protocol

from ai_trader.models import NewsItem, Sentiment

# Lower-case names and bare tickers that refer to a base asset.
ASSET_ALIASES: dict[str, str] = {
    "bitcoin": "BTC",
    "xbt": "BTC",
    "比特币": "BTC",
    "ether": "ETH",
    "ethereum": "ETH",
    "以太坊": "ETH",
    "以太": "ETH",
}


class SentimentClassifier(Protocol):
    name: str

    async def classify(self, item: NewsItem) -> Sentiment: ...


def base_asset(symbol: str) -> str:
    for quote in ("USDT", "USDC", "USD", "BUSD"):
        if symbol.endswith(quote) and len(symbol) > len(quote):
            return symbol[: -len(quote)]
    return symbol


def canonical_symbols(raw: Iterable[str], universe: Sequence[str]) -> list[str]:
    """Map tickers, names or full symbols onto universe entries, preserving first-seen
    order, dropping duplicates and anything outside the universe."""
    by_key: dict[str, str] = {}
    for sym in universe:
        by_key[sym.upper()] = sym
        by_key.setdefault(base_asset(sym.upper()), sym)
    out: list[str] = []
    for item in raw:
        token = str(item).strip()
        alias = ASSET_ALIASES.get(token.lower(), token).upper()
        match = by_key.get(alias) or by_key.get(base_asset(alias))
        if match and match not in out:
            out.append(match)
    return out
