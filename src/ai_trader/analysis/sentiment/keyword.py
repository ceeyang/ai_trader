"""Keyword-list sentiment baseline (design 5.7): deterministic, offline, and the fallback
whenever the LLM classifier is unavailable."""

import re
from collections.abc import Sequence

from ai_trader.analysis.sentiment.base import ASSET_ALIASES, base_asset
from ai_trader.models import Direction, Horizon, NewsItem, Sentiment

BULLISH_TERMS: tuple[str, ...] = (
    "etf",
    "approve",
    "approves",
    "approved",
    "approval",
    "listing",
    "will list",
    "halving",
    "rate cut",
    "rate cuts",
    "cuts rates",
    "inflow",
    "inflows",
    "all-time high",
    "rally",
    "surge",
    "adoption",
    "上市",
    "获批",
    "批准",
    "减半",
    "降息",
    "流入",
    "利好",
    "上涨",
)

BEARISH_TERMS: tuple[str, ...] = (
    "lawsuit",
    "sues",
    "hack",
    "hacked",
    "exploit",
    "exploited",
    "drain",
    "drains",
    "delist",
    "delisting",
    "delisted",
    "rate hike",
    "rate hikes",
    "hikes rates",
    "liquidation",
    "liquidations",
    "bankruptcy",
    "bankrupt",
    "ban",
    "outflow",
    "outflows",
    "crash",
    "下架",
    "退市",
    "黑客",
    "被盗",
    "加息",
    "破产",
    "爆仓",
    "清算",
    "起诉",
    "暴跌",
    "利空",
)

_CONFIDENCE_BY_HITS = {0: 0.0, 1: 0.3, 2: 0.45}
_MAX_CONFIDENCE = 0.6
_MARKET_WIDE_SYMBOL = "BTCUSDT"


def _pattern(term: str) -> re.Pattern[str]:
    # ASCII terms must stand alone as words ("listing" must not match "delisting");
    # CJK terms have no word boundaries and match as substrings.
    if term.isascii():
        return re.compile(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])")
    return re.compile(re.escape(term))


def _hits(text: str, patterns: Sequence[tuple[str, re.Pattern[str]]]) -> list[str]:
    return [term for term, pat in patterns if pat.search(text)]


class KeywordClassifier:
    name = "keyword"

    def __init__(self, universe: Sequence[str]) -> None:
        self._universe = list(universe)
        self._bull = [(t, _pattern(t)) for t in BULLISH_TERMS]
        self._bear = [(t, _pattern(t)) for t in BEARISH_TERMS]
        self._symbol_patterns: list[tuple[str, list[re.Pattern[str]]]] = []
        for sym in self._universe:
            base = base_asset(sym.upper())
            terms = {sym.lower(), base.lower()} | {name for name, b in ASSET_ALIASES.items() if b == base}
            self._symbol_patterns.append((sym, [_pattern(t) for t in sorted(terms)]))

    def _symbols(self, text: str) -> list[str]:
        found = [sym for sym, pats in self._symbol_patterns if any(p.search(text) for p in pats)]
        if found:
            return found
        if _MARKET_WIDE_SYMBOL in self._universe:
            return [_MARKET_WIDE_SYMBOL]
        return self._universe[:1]

    async def classify(self, item: NewsItem) -> Sentiment:
        text = f"{item.title}\n{item.text}".lower()
        bull = _hits(text, self._bull)
        bear = _hits(text, self._bear)
        if len(bull) > len(bear):
            direction, winners = Direction.BULLISH, len(bull)
        elif len(bear) > len(bull):
            direction, winners = Direction.BEARISH, len(bear)
        else:
            direction, winners = Direction.NEUTRAL, 0
        confidence = _CONFIDENCE_BY_HITS.get(winners, _MAX_CONFIDENCE)
        symbols = self._symbols(text) if direction != Direction.NEUTRAL else []
        return Sentiment(
            direction=direction,
            confidence=confidence,
            symbols=symbols,
            horizon=Horizon.HOURS,
            rationale=f"keyword hits bullish={bull} bearish={bear}",
            model=self.name,
        )
