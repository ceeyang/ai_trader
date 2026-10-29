"""X (Twitter) recent-search news source with a daily request budget (design 5.5)."""

import logging
import time
from collections.abc import Callable
from datetime import UTC, date, datetime

import httpx

from ai_trader.data.news.base import DailyBudget
from ai_trader.models import NewsItem, utc_now

log = logging.getLogger(__name__)

_SEARCH_URL = "https://api.x.com/2/tweets/search/recent"
_DEFAULT_BACKOFF_S = 900


def _utc_date(ts: float) -> date:
    return datetime.fromtimestamp(ts, tz=UTC).date()


class XSearchSource:
    """Polls X's recent-search endpoint for `query`, consuming `max_results` units of
    `budget` per request attempt (design 5.5). Tracks `since_id` across calls so repeat
    fetches only ask for tweets newer than the last batch. A spent budget or an active
    429 back-off both short-circuit to an empty list without making a request; any other
    non-200 response or transport error refunds the budget and is logged, never raised.
    The bearer token is used only in the Authorization header and is never logged."""

    name = "x"

    def __init__(
        self,
        bearer_token: str,
        query: str,
        http: httpx.AsyncClient,
        budget: DailyBudget,
        *,
        max_results: int = 10,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._token = bearer_token
        self._query = query
        self._http = http
        self._budget = budget
        self._max_results = max_results
        self._clock = clock
        self._since_id: str | None = None
        self._budget_warned_day: date | None = None
        self.next_allowed_at: float = 0.0

    async def fetch(self) -> list[NewsItem]:
        if self._clock() < self.next_allowed_at:
            return []

        if not self._budget.try_consume(self._max_results):
            today = _utc_date(self._clock())
            if self._budget_warned_day != today:
                log.warning("XSearchSource %r: daily budget exhausted, skipping fetch", self._query)
                self._budget_warned_day = today
            return []

        params: dict[str, str | int] = {
            "query": self._query,
            "max_results": self._max_results,
            "tweet.fields": "created_at,author_id,public_metrics",
            "expansions": "author_id",
            "user.fields": "username",
        }
        if self._since_id is not None:
            params["since_id"] = self._since_id

        try:
            response = await self._http.get(
                _SEARCH_URL, params=params, headers={"Authorization": f"Bearer {self._token}"}
            )
        except httpx.HTTPError:
            self._budget.refund(self._max_results)
            log.warning("XSearchSource %r: request failed", self._query, exc_info=True)
            return []

        if response.status_code == 429:
            self._budget.refund(self._max_results)
            reset = response.headers.get("x-rate-limit-reset")
            self.next_allowed_at = (
                float(reset) if reset is not None else self._clock() + _DEFAULT_BACKOFF_S
            )
            log.warning(
                "XSearchSource %r: rate limited, backing off until %s", self._query, self.next_allowed_at
            )
            return []

        if response.status_code != 200:
            self._budget.refund(self._max_results)
            log.warning("XSearchSource %r: unexpected status %s", self._query, response.status_code)
            return []

        # A single guard around decoding the body and pulling the shape we rely on: any
        # failure here (invalid JSON, or a 200 body that isn't shaped like X's search
        # response) must still refund the full `max_results` consumed above, since no
        # usable result count was ever established.
        try:
            payload = response.json()
            tweets = payload.get("data", [])
            newest_id = payload.get("meta", {}).get("newest_id")
            users = {u["id"]: u["username"] for u in payload.get("includes", {}).get("users", [])}
        except (ValueError, AttributeError, TypeError, KeyError):
            self._budget.refund(self._max_results)
            log.warning("XSearchSource %r: malformed response body", self._query, exc_info=True)
            return []

        self._budget.refund(self._max_results - len(tweets))
        if newest_id is not None:
            self._since_id = newest_id

        items = []
        for tweet in tweets:
            try:
                items.append(self._to_news_item(tweet, users))
            except (AttributeError, KeyError, TypeError, ValueError):
                log.warning("XSearchSource %r: skipping malformed tweet record", self._query, exc_info=True)
        return items

    def _to_news_item(self, tweet: dict, users: dict[str, str]) -> NewsItem:
        tweet_id = tweet["id"]
        author_id = tweet.get("author_id")
        username = users.get(author_id) if isinstance(author_id, str) else None
        text = tweet.get("text", "")
        return NewsItem(
            id=f"x:{tweet_id}",
            source="x",
            author=username,
            title=text[:120],
            text=text,
            url=f"https://x.com/{username}/status/{tweet_id}" if username else None,
            published_at=datetime.fromisoformat(tweet["created_at"]),
            fetched_at=utc_now(),
        )
