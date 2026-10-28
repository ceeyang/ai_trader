"""DeepSeek sentiment classifier (design 5.7): calls DeepSeek's OpenAI-compatible
chat-completions endpoint in JSON mode and falls back to a keyword classifier whenever
the budget is spent or the call fails in any way."""

import logging
from collections.abc import Sequence
from typing import Literal

import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator

from ai_trader.analysis.sentiment.base import SentimentClassifier, canonical_symbols
from ai_trader.data.news.base import DailyBudget
from ai_trader.models import Direction, Horizon, NewsItem, Sentiment

log = logging.getLogger(__name__)

FALLBACK_MODEL = "keyword-fallback"
TRUNCATION_MARKER = "[truncated]"

# `{universe}` is filled in per classifier. DeepSeek's json_object mode requires the
# prompt to mention "json".
SYSTEM = (
    "You are a crypto market analyst. Judge the likely short-term impact of one news item "
    "or social post on USDT-margined perpetual futures prices.\n"
    "Tradable symbols: {universe}. Only use symbols from this list; news about the whole "
    "crypto market (macro, regulation, exchanges in general) maps to BTCUSDT.\n"
    "Reply with a single json object with exactly these keys:\n"
    '- "direction": "bullish", "bearish" or "neutral"\n'
    '- "confidence": number from 0 to 1\n'
    '- "symbols": list of affected symbols from the list above\n'
    '- "horizon": "minutes", "hours" or "days"\n'
    '- "rationale": one short sentence\n'
    "Confidence calibration: official, surprising news directly tied to price (approvals, "
    "listings, hacks, rate decisions, bankruptcies) -> high (0.7-1.0); rumours, marketing, "
    "memes, opinion or old news -> neutral or low (below 0.4)."
)


def build_system_prompt(universe: Sequence[str]) -> str:
    return SYSTEM.format(universe=", ".join(universe))


class SentimentOutput(BaseModel):
    direction: Literal["bullish", "bearish", "neutral"]
    confidence: float = Field(allow_inf_nan=False)
    symbols: list[str]
    horizon: Literal["minutes", "hours", "days"]
    rationale: str

    @field_validator("confidence")
    @classmethod
    def _clamp(cls, v: float) -> float:
        return min(1.0, max(0.0, v))


class DeepSeekClassifier:
    def __init__(
        self,
        http: httpx.AsyncClient,
        api_key: str,
        universe: Sequence[str],
        *,
        model: str = "deepseek-chat",
        base_url: str = "https://api.deepseek.com",
        fallback: SentimentClassifier,
        budget: DailyBudget,
        max_text_chars: int = 4000,
        timeout_s: float = 30.0,
    ) -> None:
        self._http = http
        self._api_key = api_key
        self._universe = list(universe)
        self.model = model
        self.name = model
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._fallback = fallback
        self._budget = budget
        self._max_text_chars = max_text_chars
        self._timeout_s = timeout_s
        self._system = build_system_prompt(self._universe)

    def _user_content(self, item: NewsItem) -> str:
        text = item.text
        if len(text) > self._max_text_chars:
            text = f"{text[: self._max_text_chars]} {TRUNCATION_MARKER}"
        return (
            f"source: {item.source}\n"
            f"author: {item.author or '-'}\n"
            f"published_at: {item.published_at.isoformat()}\n"
            f"title: {item.title}\n"
            f"text: {text}"
        )

    async def _fall_back(self, item: NewsItem) -> Sentiment:
        sentiment = await self._fallback.classify(item)
        return sentiment.model_copy(update={"model": FALLBACK_MODEL})

    async def _request(self, item: NewsItem) -> SentimentOutput | None:
        body = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": 512,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": self._system},
                {"role": "user", "content": self._user_content(item)},
            ],
        }
        try:
            response = await self._http.post(
                self._url,
                json=body,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=self._timeout_s,
            )
        except httpx.HTTPError as exc:
            # Log only the exception type: never the request, whose headers hold the key.
            log.warning("DeepSeek request for news %s failed: %s", item.id, type(exc).__name__)
            return None
        if not response.is_success:
            log.warning("DeepSeek returned status %s for news %s", response.status_code, item.id)
            return None
        try:
            content = response.json()["choices"][0]["message"]["content"]
            return SentimentOutput.model_validate_json(content)
        except (ValueError, KeyError, IndexError, TypeError, ValidationError) as exc:
            log.warning("DeepSeek response for news %s unusable: %s", item.id, type(exc).__name__)
            return None

    async def classify(self, item: NewsItem) -> Sentiment:
        if not self._budget.try_consume():
            log.warning("DeepSeek daily budget exhausted; using keyword fallback for news %s", item.id)
            return await self._fall_back(item)
        out = await self._request(item)
        if out is None:
            self._budget.refund(1)
            return await self._fall_back(item)
        return Sentiment(
            direction=Direction(out.direction),
            confidence=out.confidence,
            symbols=canonical_symbols(out.symbols, self._universe),
            horizon=Horizon(out.horizon),
            rationale=out.rationale,
            model=self.model,
        )
