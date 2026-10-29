"""News-sentiment detector (design 5.6/5.7): classifies each `NewsItem`, persists the
sentiment, and turns confident directional calls into one `Signal` per symbol.

Signals are tagged `detector="news_keyword"` when the sentiment came from the keyword
classifier (`model` "keyword" or "keyword-fallback") and `"news_sentiment"` otherwise, so
the aggregator weighs — and the AutoTuner tunes — the two kinds of evidence separately.

Items published more than `NewsConfig.max_news_age_s` ago (read at call time) are not
classified at all — no LLM call is spent on them — and emit nothing; the poller has
already stored them. `stale_skipped` counts them for the health log.
"""

import logging
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta

from ai_trader.analysis.sentiment.base import SentimentClassifier
from ai_trader.data.market_state import MarketState
from ai_trader.models import Direction, Horizon, NewsItem, Signal, new_id
from ai_trader.settings import DetectorConfig, NewsConfig
from ai_trader.storage.db import Store

log = logging.getLogger(__name__)

HORIZON_TTL: dict[Horizon, timedelta] = {
    Horizon.MINUTES: timedelta(minutes=30),
    Horizon.HOURS: timedelta(hours=4),
    Horizon.DAYS: timedelta(hours=24),
}
KEYWORD_MODELS = frozenset({"keyword", "keyword-fallback"})
KEYWORD_DETECTOR = "news_keyword"


class NewsSentimentDetector:
    """Reads its confidence threshold on every event (an explicit `min_confidence`, else
    `cfg.news_min_confidence`) so a later AutoTuner can retune it live."""

    name = "news_sentiment"
    subscribes_to: tuple[type, ...] = (NewsItem,)

    def __init__(
        self,
        classifier: SentimentClassifier,
        universe: Sequence[str],
        store: Store,
        state: MarketState,
        cfg: DetectorConfig | None = None,
        *,
        min_confidence: float | None = None,
        news_cfg: NewsConfig | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._classifier = classifier
        self._universe = set(universe)
        self._store = store
        self._state = state
        self._cfg = cfg if cfg is not None else DetectorConfig()
        self._min_confidence = min_confidence
        self._news_cfg = news_cfg if news_cfg is not None else NewsConfig()
        self._clock = clock
        self.stale_skipped = 0

    def _threshold(self) -> float:
        if self._min_confidence is not None:
            return self._min_confidence
        return self._cfg.news_min_confidence

    async def on_event(self, event: NewsItem) -> list[Signal]:
        item = event
        now = datetime.fromtimestamp(self._clock(), UTC)
        if item.published_at < now - timedelta(seconds=self._news_cfg.max_news_age_s):
            self.stale_skipped += 1
            log.debug(
                "news %s published %s is older than %ss; not classified",
                item.id,
                item.published_at.isoformat(),
                self._news_cfg.max_news_age_s,
            )
            # INSERT OR IGNORE: normally the poller stored it already.
            await self._store.insert_news(item)
            return []
        sentiment = await self._classifier.classify(item)
        # `sentiments.news_id` references `news`; the poller normally stored the item
        # already, and INSERT OR IGNORE makes this a no-op in that case.
        await self._store.insert_news(item)
        await self._store.insert_sentiment(item.id, sentiment)
        if sentiment.direction == Direction.NEUTRAL or sentiment.confidence < self._threshold():
            return []
        detector = KEYWORD_DETECTOR if sentiment.model in KEYWORD_MODELS else self.name
        expires_at = now + HORIZON_TTL[sentiment.horizon]
        signals: list[Signal] = []
        for symbol in sentiment.symbols:
            if symbol not in self._universe:
                continue
            mark = self._state.mark(symbol)
            if mark is None:
                continue
            signals.append(
                Signal(
                    id=new_id(),
                    detector=detector,
                    symbol=symbol,
                    direction=sentiment.direction,
                    strength=sentiment.confidence,
                    created_at=now,
                    expires_at=expires_at,
                    ref_price=mark.mark_price,
                    rationale=sentiment.rationale,
                    meta={"news_id": item.id, "model": sentiment.model},
                )
            )
        return signals
