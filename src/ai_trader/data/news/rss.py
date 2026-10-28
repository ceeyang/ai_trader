"""RSS news source (design 5.5)."""

import logging
import re
from calendar import timegm
from datetime import UTC, datetime
from hashlib import sha1

import feedparser
import httpx

from ai_trader.models import NewsItem, utc_now

log = logging.getLogger(__name__)

_USER_AGENT = "Mozilla/5.0 (compatible; ai-trader/2.0)"
_TAG_RE = re.compile(r"<[^>]+>")


class RssSource:
    """Fetches `url` as an RSS/Atom feed via `http` and maps each entry to a `NewsItem`
    (design 5.5). A non-2xx response or a feed that fails to parse is logged and treated
    as an empty batch rather than raised, so one bad feed never stops the poller's other
    sources."""

    def __init__(self, name: str, url: str, http: httpx.AsyncClient) -> None:
        self.name = name
        self._url = url
        self._http = http

    async def fetch(self) -> list[NewsItem]:
        try:
            response = await self._http.get(self._url, headers={"User-Agent": _USER_AGENT})
        except httpx.HTTPError:
            log.warning("RssSource %r: request to %s failed", self.name, self._url, exc_info=True)
            return []

        if response.status_code // 100 != 2:
            log.warning("RssSource %r: %s returned status %s", self.name, self._url, response.status_code)
            return []

        try:
            parsed = feedparser.parse(response.content)
        except Exception:
            log.warning("RssSource %r: failed to parse feed from %s", self.name, self._url, exc_info=True)
            return []

        if parsed.bozo:
            log.warning(
                "RssSource %r: feed from %s failed to parse: %s",
                self.name,
                self._url,
                parsed.get("bozo_exception"),
            )
            return []

        return [self._to_news_item(entry) for entry in parsed.entries]

    def _to_news_item(self, entry) -> NewsItem:
        title = entry.get("title", "")
        link = entry.get("link")
        summary = entry.get("summary", "")
        return NewsItem(
            id=sha1((entry.get("id") or link or title).encode()).hexdigest(),
            source=self.name,
            author=entry.get("author"),
            title=title,
            text=_TAG_RE.sub("", summary).strip(),
            url=link,
            published_at=_parse_published(entry) or utc_now(),
            fetched_at=utc_now(),
            raw={"title": title, "link": link, "id": entry.get("id"), "published": entry.get("published")},
        )


def _parse_published(entry) -> datetime | None:
    struct = entry.get("published_parsed") or entry.get("updated_parsed")
    if struct is None:
        return None
    return datetime.fromtimestamp(timegm(struct), tz=UTC)
