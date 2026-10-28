import json
from datetime import timedelta

import httpx
import respx
from conftest import make_mark_price, make_news

from ai_trader.analysis.detectors.news_sentiment import NewsSentimentDetector
from ai_trader.analysis.sentiment.base import canonical_symbols
from ai_trader.analysis.sentiment.deepseek import DeepSeekClassifier
from ai_trader.analysis.sentiment.keyword import KeywordClassifier
from ai_trader.data.market_state import MarketState
from ai_trader.data.news.base import DailyBudget
from ai_trader.models import Direction, Horizon, Sentiment
from ai_trader.settings import DetectorConfig, Settings
from ai_trader.storage.db import Store

UNI = ["BTCUSDT", "ETHUSDT"]
DS = "https://api.deepseek.com/chat/completions"


def ds_response(obj, content=None):
    return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": content if content is not None else json.dumps(obj)}}],
                                     "usage": {"prompt_tokens": 100, "completion_tokens": 20}})


def mk(budget=None, **kw):
    return DeepSeekClassifier(httpx.AsyncClient(), "sk-test", UNI, fallback=KeywordClassifier(UNI), budget=budget or DailyBudget(10), **kw)


def test_canonical_symbols(): assert canonical_symbols(["btc", "ETHUSDT", "DOGE", "Bitcoin"], UNI) == ["BTCUSDT", "ETHUSDT"]


async def test_keyword_classifier_bearish_hack():
    s = await KeywordClassifier(UNI).classify(make_news("n", title="Major exchange hack drains ETH", text=""))
    assert s.direction == Direction.BEARISH and s.symbols == ["ETHUSDT"] and 0.3 <= s.confidence <= 0.6 and s.model == "keyword"


async def test_keyword_classifier_neutral_without_hits():
    s = await KeywordClassifier(UNI).classify(make_news("n", title="Weekly newsletter", text="hello"))
    assert s.direction == Direction.NEUTRAL and s.confidence == 0.0


async def test_keyword_classifier_chinese_and_scaling():
    s = await KeywordClassifier(UNI).classify(make_news("n", title="比特币ETF获批 利好", text="SEC 降息"))
    assert s.direction == Direction.BULLISH and s.symbols == ["BTCUSDT"] and s.confidence == 0.6


async def test_keyword_classifier_tie_is_neutral():
    s = await KeywordClassifier(UNI).classify(make_news("n", title="Halving ahead but exchange hack", text=""))
    assert s.direction == Direction.NEUTRAL and s.confidence == 0.0


@respx.mock
async def test_deepseek_classifier_parses_and_canonicalizes():
    route = respx.post(DS).mock(return_value=ds_response({"direction": "bullish", "confidence": 0.8, "symbols": ["BTC", "XRP"], "horizon": "hours", "rationale": "ETF inflow"}))
    s = await mk().classify(make_news("n", title="Spot BTC ETF sees record inflow", text="..."))
    assert s.direction == Direction.BULLISH and s.symbols == ["BTCUSDT"] and s.model == "deepseek-chat" and s.confidence == 0.8 and s.horizon == Horizon.HOURS
    req = route.calls.last.request; body = json.loads(req.content)
    assert req.headers["Authorization"] == "Bearer sk-test"
    assert body["model"] == "deepseek-chat" and body["response_format"] == {"type": "json_object"} and body["temperature"] == 0 and body["max_tokens"] == 512
    assert body["messages"][0]["role"] == "system" and "BTCUSDT" in body["messages"][0]["content"] and "json" in body["messages"][0]["content"].lower()
    assert body["messages"][1]["role"] == "user" and "Spot BTC ETF" in body["messages"][1]["content"]


@respx.mock
async def test_confidence_clamped():
    respx.post(DS).mock(return_value=ds_response({"direction": "bullish", "confidence": 1.7, "symbols": ["ETH"], "horizon": "minutes", "rationale": "r"}))
    s = await mk().classify(make_news("n"))
    assert s.confidence == 1.0 and s.symbols == ["ETHUSDT"]


@respx.mock
async def test_unknown_symbols_dropped():
    respx.post(DS).mock(return_value=ds_response({"direction": "bullish", "confidence": 0.9, "symbols": ["DOGE"], "horizon": "days", "rationale": "r"}))
    assert (await mk().classify(make_news("n"))).symbols == []


@respx.mock
async def test_malformed_json_falls_back_to_keyword():
    respx.post(DS).mock(return_value=ds_response(None, content="not json at all"))
    s = await mk().classify(make_news("n", title="Exchange hack", text=""))
    assert s.model == "keyword-fallback" and s.direction == Direction.BEARISH


@respx.mock
async def test_schema_violation_falls_back_and_refunds():
    budget = DailyBudget(10)
    respx.post(DS).mock(return_value=ds_response({"direction": "up", "confidence": 0.5}))
    s = await mk(budget).classify(make_news("n", title="Exchange hack", text=""))
    assert s.model == "keyword-fallback" and budget.remaining == 10


@respx.mock
async def test_http_error_falls_back_to_keyword():
    budget = DailyBudget(10)
    respx.post(DS).mock(return_value=httpx.Response(500, json={"error": "boom"}))
    assert (await mk(budget).classify(make_news("n", title="Exchange hack", text=""))).model == "keyword-fallback"
    assert budget.remaining == 10


@respx.mock
async def test_timeout_falls_back_to_keyword():
    budget = DailyBudget(10)
    respx.post(DS).mock(side_effect=httpx.ReadTimeout("t"))
    assert (await mk(budget).classify(make_news("n", title="Exchange hack", text=""))).model == "keyword-fallback"
    assert budget.remaining == 10


@respx.mock
async def test_success_consumes_budget():
    budget = DailyBudget(10)
    respx.post(DS).mock(return_value=ds_response({"direction": "neutral", "confidence": 0, "symbols": [], "horizon": "days", "rationale": ""}))
    await mk(budget).classify(make_news("n"))
    assert budget.remaining == 9


@respx.mock
async def test_budget_exhausted_uses_fallback_without_calling_api():
    route = respx.post(DS).mock(return_value=ds_response({"direction": "neutral", "confidence": 0, "symbols": [], "horizon": "days", "rationale": ""}))
    s = await mk(DailyBudget(0)).classify(make_news("n", title="hack", text=""))
    assert route.call_count == 0 and s.model == "keyword-fallback"


@respx.mock
async def test_long_text_truncated():
    route = respx.post(DS).mock(return_value=ds_response({"direction": "neutral", "confidence": 0, "symbols": [], "horizon": "days", "rationale": ""}))
    await mk().classify(make_news("n", title="t", text="z" * 10000))
    content = json.loads(route.calls.last.request.content)["messages"][1]["content"]
    assert "[truncated]" in content and content.count("z") <= 4000


def test_settings_llm_defaults(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-abc")
    s = Settings(_env_file=None)
    assert s.llm.provider == "deepseek" and s.llm.model == "deepseek-chat" and s.llm.base_url == "https://api.deepseek.com" and s.llm.daily_call_budget == 500
    assert s.deepseek_api_key.get_secret_value() == "sk-abc" and "sk-abc" not in repr(s)


class C:
    name = "fake"

    def __init__(self, conf, horizon=Horizon.HOURS, direction=Direction.BULLISH):
        self.conf = conf
        self.horizon = horizon
        self.direction = direction

    async def classify(self, item):
        return Sentiment(direction=self.direction, confidence=self.conf, symbols=UNI, horizon=self.horizon, rationale="r", model="fake")


async def _store_and_state(tmp_path, symbols=UNI):
    st = Store(tmp_path / "t.db")
    await st.open()
    state = MarketState()
    for sym in symbols:
        state.update_mark(make_mark_price(symbol=sym))
    return st, state


async def test_news_detector_emits_per_symbol_and_filters_low_confidence(tmp_path):
    st, state = await _store_and_state(tmp_path)
    try:
        det = NewsSentimentDetector(C(0.7), UNI, st, state, min_confidence=0.6)
        sigs = await det.on_event(make_news("n1"))
        assert [s.symbol for s in sigs] == UNI and sigs[0].strength == 0.7 and sigs[0].expires_at - sigs[0].created_at == timedelta(hours=4) and sigs[0].detector == "news_sentiment"
        assert sigs[0].meta == {"news_id": "n1", "model": "fake"} and sigs[0].direction == Direction.BULLISH
        assert await NewsSentimentDetector(C(0.5), UNI, st, state, min_confidence=0.6).on_event(make_news("n2")) == []
        assert await st.count("sentiments") == 2
    finally:
        await st.close()


async def test_news_detector_neutral_silent_and_skips_symbols_without_mark(tmp_path):
    st, state = await _store_and_state(tmp_path, symbols=["ETHUSDT"])
    try:
        neutral = NewsSentimentDetector(C(0.9, direction=Direction.NEUTRAL), UNI, st, state, min_confidence=0.6)
        assert await neutral.on_event(make_news("n1")) == []
        det = NewsSentimentDetector(C(0.9, horizon=Horizon.MINUTES), UNI, st, state, min_confidence=0.6)
        sigs = await det.on_event(make_news("n2"))
        assert [s.symbol for s in sigs] == ["ETHUSDT"]
        assert sigs[0].expires_at - sigs[0].created_at == timedelta(minutes=30)
        days = NewsSentimentDetector(C(0.9, horizon=Horizon.DAYS), UNI, st, state, min_confidence=0.6)
        sigs = await days.on_event(make_news("n3"))
        assert sigs[0].expires_at - sigs[0].created_at == timedelta(hours=24)
        assert await st.count("sentiments") == 3
    finally:
        await st.close()


async def test_news_detector_reads_cfg_threshold_at_call_time(tmp_path):
    st, state = await _store_and_state(tmp_path)
    try:
        cfg = DetectorConfig()
        det = NewsSentimentDetector(C(0.5), UNI, st, state, cfg)
        assert await det.on_event(make_news("n1")) == []
        cfg.news_min_confidence = 0.4
        sigs = await det.on_event(make_news("n2"))
        assert len(sigs) == 2 and {s.symbol for s in sigs} == set(UNI)
    finally:
        await st.close()
