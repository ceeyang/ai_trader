# tests/unit/test_news_sources.py
import asyncio
import json
import logging
import pathlib
import time

import httpx
import respx
from conftest import _append, make_news

from ai_trader.bus import EventBus
from ai_trader.data.news.base import DailyBudget
from ai_trader.data.news.poller import NewsPoller
from ai_trader.data.news.rss import RssSource
from ai_trader.data.news.x_api import XSearchSource
from ai_trader.models import NewsItem
from ai_trader.storage.db import Store

FXN = pathlib.Path(__file__).parents[1] / "fixtures" / "news"


def fxn(name):
    return json.loads((FXN / name).read_text())


# ---- RssSource --------------------------------------------------------------


@respx.mock
async def test_rss_source_parses_entries():
    respx.get("https://feed.example/rss").mock(
        return_value=httpx.Response(200, content=(FXN / "sample.rss").read_bytes())
    )
    items = await RssSource("coindesk", "https://feed.example/rss", httpx.AsyncClient()).fetch()
    assert len(items) == 2 and items[0].source == "coindesk" and items[0].published_at.tzinfo is not None and items[0].id


@respx.mock
async def test_rss_source_sends_user_agent_header():
    route = respx.get("https://feed.example/rss").mock(
        return_value=httpx.Response(200, content=(FXN / "sample.rss").read_bytes())
    )
    await RssSource("coindesk", "https://feed.example/rss", httpx.AsyncClient()).fetch()
    assert route.calls.last.request.headers["User-Agent"] == "Mozilla/5.0 (compatible; ai-trader/2.0)"


@respx.mock
async def test_rss_source_non_2xx_returns_empty():
    respx.get("https://feed.example/rss").mock(return_value=httpx.Response(403))
    items = await RssSource("coindesk", "https://feed.example/rss", httpx.AsyncClient()).fetch()
    assert items == []


@respx.mock
async def test_rss_source_unparseable_feed_returns_empty():
    respx.get("https://feed.example/rss").mock(return_value=httpx.Response(200, content=b"not xml at all"))
    items = await RssSource("coindesk", "https://feed.example/rss", httpx.AsyncClient()).fetch()
    assert items == []


# ---- XSearchSource ------------------------------------------------------------


@respx.mock
async def test_x_source_query_params_since_id_and_author():
    route = respx.get("https://api.x.com/2/tweets/search/recent").mock(
        return_value=httpx.Response(200, json=fxn("x_search.json"))
    )
    src = XSearchSource("TOKEN", "from:binance", httpx.AsyncClient(), DailyBudget(100), max_results=10)
    items = await src.fetch()
    q = dict(route.calls.last.request.url.params)
    assert q["query"] == "from:binance" and q["max_results"] == "10" and "since_id" not in q
    assert route.calls.last.request.headers["Authorization"] == "Bearer TOKEN"
    assert items[0].id.startswith("x:") and items[0].author == fxn("x_search.json")["includes"]["users"][0]["username"]
    await src.fetch()
    assert dict(route.calls.last.request.url.params)["since_id"] == fxn("x_search.json")["meta"]["newest_id"]


@respx.mock
async def test_x_source_refunds_unused_budget_on_success():
    respx.get("https://api.x.com/2/tweets/search/recent").mock(
        return_value=httpx.Response(200, json=fxn("x_search.json"))
    )
    budget = DailyBudget(100)
    src = XSearchSource("T", "q", httpx.AsyncClient(), budget, max_results=10)
    items = await src.fetch()
    assert len(items) == 2 and budget.remaining == 98  # consumed 10, refunded 10-2=8


@respx.mock
async def test_x_source_respects_daily_budget():
    route = respx.get("https://api.x.com/2/tweets/search/recent").mock(
        return_value=httpx.Response(200, json=fxn("x_search.json"))
    )
    src = XSearchSource("T", "q", httpx.AsyncClient(), DailyBudget(1), max_results=10)
    assert await src.fetch() == [] and route.call_count == 0


@respx.mock
async def test_x_source_budget_exhausted_warns_once(caplog):
    respx.get("https://api.x.com/2/tweets/search/recent").mock(
        return_value=httpx.Response(200, json=fxn("x_search.json"))
    )
    src = XSearchSource("T", "q", httpx.AsyncClient(), DailyBudget(0), max_results=10)
    with caplog.at_level(logging.WARNING):
        await src.fetch()
        await src.fetch()
    assert sum("budget exhausted" in r.message for r in caplog.records) == 1


def test_daily_budget_resets_on_utc_day_change():
    t = [1_700_000_000.0]
    b = DailyBudget(2, clock=lambda: t[0])
    assert b.try_consume(2) and not b.try_consume(1)
    t[0] += 86400
    assert b.try_consume(1)


@respx.mock
async def test_x_source_429_backs_off():
    respx.get("https://api.x.com/2/tweets/search/recent").mock(
        return_value=httpx.Response(429, headers={"x-rate-limit-reset": str(int(time.time()) + 900)})
    )
    src = XSearchSource("T", "q", httpx.AsyncClient(), DailyBudget(100))
    assert await src.fetch() == [] and src.next_allowed_at > time.time() + 800


@respx.mock
async def test_x_source_429_refunds_budget():
    respx.get("https://api.x.com/2/tweets/search/recent").mock(
        return_value=httpx.Response(429, headers={"x-rate-limit-reset": str(int(time.time()) + 900)})
    )
    budget = DailyBudget(10)
    src = XSearchSource("T", "q", httpx.AsyncClient(), budget, max_results=10)
    await src.fetch()
    assert budget.remaining == 10


@respx.mock
async def test_x_source_429_fallback_backoff_when_header_missing():
    respx.get("https://api.x.com/2/tweets/search/recent").mock(return_value=httpx.Response(429))
    t = [1_700_000_000.0]
    src = XSearchSource("T", "q", httpx.AsyncClient(), DailyBudget(100), clock=lambda: t[0])
    await src.fetch()
    assert src.next_allowed_at == t[0] + 900


@respx.mock
async def test_x_source_backs_off_without_requesting_while_rate_limited():
    route = respx.get("https://api.x.com/2/tweets/search/recent").mock(
        return_value=httpx.Response(429, headers={"x-rate-limit-reset": str(int(time.time()) + 900)})
    )
    t = [0.0]
    src = XSearchSource("T", "q", httpx.AsyncClient(), DailyBudget(100), clock=lambda: t[0])
    await src.fetch()
    assert route.call_count == 1
    assert await src.fetch() == [] and route.call_count == 1


@respx.mock
async def test_x_source_other_error_status_refunds_budget():
    respx.get("https://api.x.com/2/tweets/search/recent").mock(return_value=httpx.Response(500))
    budget = DailyBudget(10)
    src = XSearchSource("T", "q", httpx.AsyncClient(), budget, max_results=10)
    assert await src.fetch() == [] and budget.remaining == 10


@respx.mock
async def test_x_source_transport_error_refunds_budget():
    respx.get("https://api.x.com/2/tweets/search/recent").mock(side_effect=httpx.ConnectError("x"))
    budget = DailyBudget(10)
    src = XSearchSource("T", "q", httpx.AsyncClient(), budget, max_results=10)
    assert await src.fetch() == [] and budget.remaining == 10


@respx.mock
async def test_x_source_never_logs_the_token(caplog):
    respx.get("https://api.x.com/2/tweets/search/recent").mock(
        return_value=httpx.Response(429, headers={"x-rate-limit-reset": str(int(time.time()) + 900)})
    )
    with caplog.at_level(logging.WARNING):
        await XSearchSource("SUPER-SECRET-TOKEN", "q", httpx.AsyncClient(), DailyBudget(100)).fetch()
    assert "SUPER-SECRET-TOKEN" not in caplog.text


# ---- NewsPoller --------------------------------------------------------------


async def test_poller_dedupes_and_publishes(tmp_path):
    class Src:
        name = "fake"

        async def fetch(self):
            return [make_news("same")]

    st = Store(tmp_path / "t.db")
    await st.open()
    bus = EventBus()
    got = []
    bus.subscribe(NewsItem, lambda e: _append(got, e))
    poller = NewsPoller(bus, st, [(Src(), 1)])
    await bus.start()
    await poller.poll_once()
    await poller.poll_once()
    await bus.drain()
    await bus.stop()
    assert len(got) == 1
    await st.close()


async def test_poller_isolates_source_failures(tmp_path):
    class Bad:
        name = "bad"

        async def fetch(self):
            raise RuntimeError("boom")

    class Good:
        name = "good"

        async def fetch(self):
            return [make_news("ok")]

    st = Store(tmp_path / "t.db")
    await st.open()
    bus = EventBus()
    got = []
    bus.subscribe(NewsItem, lambda e: _append(got, e))
    poller = NewsPoller(bus, st, [(Bad(), 1), (Good(), 1)])
    await bus.start()
    await poller.poll_once()
    await bus.drain()
    await bus.stop()
    assert len(got) == 1 and got[0].id == "ok"
    await st.close()


async def test_poller_run_polls_each_source_until_stopped(tmp_path):
    calls = []

    class Src:
        name = "fake"

        async def fetch(self):
            calls.append(1)
            return []

    st = Store(tmp_path / "t.db")
    await st.open()
    bus = EventBus()
    poller = NewsPoller(bus, st, [(Src(), 0.01)])
    await bus.start()
    task = asyncio.create_task(poller.run())
    await asyncio.sleep(0.05)
    await poller.stop()
    await task
    await bus.stop()
    assert len(calls) >= 2
    await st.close()
