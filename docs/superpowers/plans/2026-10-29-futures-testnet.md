# 币安合约测试网交易系统 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从零构建一个 asyncio 守护进程，接入币安 USDT 本位合约测试网的实时行情与用户数据流，融合行情探测器与新闻/X 情绪信号，经独立风控后在测试网（或模拟盘）自动开平仓，并把每个信号的前瞻收益落库。

**Architecture:** 单进程、事件总线驱动（`EventBus` 按类型分发，每订阅者独立队列）。数据层（WS 行情、RSS/X 轮询）→ 探测器（资金费率、清算、新闻情绪）→ 信号聚合 → 风控引擎 → 执行服务 → `Broker` 接口（`PaperBroker` / `BinanceFuturesBroker`）。SQLite 记录全链路；CLI 负责探测、运行、杀开关与报表。

**Tech Stack:** Python 3.12, uv, httpx, websockets, pydantic v2 + pydantic-settings, anthropic, aiosqlite, typer, feedparser; 测试 pytest + pytest-asyncio + respx。

**Spec:** `docs/superpowers/specs/2026-10-29-futures-testnet-design.md`（下文"设计稿"）。每个任务的接口以设计稿第 5 节为准，本计划中的签名与之逐字一致。

## Global Constraints

- Python `>=3.12`；`src/ai_trader` 布局；全部 I/O 异步；无同步 `requests`。
- 价格、数量、金额一律 `Decimal`；所有 `datetime` 带 `timezone.utc`。
- 默认 REST `https://testnet.binancefuture.com`，默认 WS `wss://stream.binancefuture.com`；主网 URL 仅在 `binance_testnet=False` 时推导。
- 任何订单必须经 `RiskEngine.evaluate` 批准后才能到达 `Broker.submit`（`KillSwitch` 的平仓/撤单除外）。
- 日志禁止输出 API key / secret / bearer token / 签名查询串。
- 单元测试禁止真实网络；时钟全部可注入（`clock` 参数）。
- LLM 分类器使用 DeepSeek（OpenAI 兼容 `POST {base_url}/chat/completions`，`model="deepseek-chat"`，`response_format={"type":"json_object"}`，`temperature=0`，`max_tokens=512`，通过项目已有的 `httpx` 调用，不引入 `anthropic`/`openai` SDK）；key 来自 `.env` 的 `DEEPSEEK_API_KEY`，禁止出现在日志。
- Git 提交信息不带任何 Claude 署名或 "Generated with" 字样。
- 每个任务结束前运行 `uv run pytest -q` 必须全绿，`uv run ruff check .` 无错误。

## Review Focus

1. **名义额换算出的数量低于 `min_qty` 或名义低于 `min_notional`**：必须抛 `FilterViolation` 并由 `ExecutionService` 记录、跳过，绝不能把非法数量发到交易所。（Task 3 `test_qty_for_notional_below_min_notional_raises`；Task 12 `test_open_skipped_when_filter_violation`）
2. **下单请求超时但交易所已成交**：`BinanceFuturesBroker.submit` 必须先按 `client_order_id` 查单，查到则不重发。（Task 12 `test_submit_timeout_then_found_does_not_resend`）
3. **行情陈旧期间**：`RiskEngine` 拒绝新开仓（`data_stale`），但 CLOSE 仍放行。（Task 11 `test_stale_blocks_open_but_allows_close`）
4. **UTC 日切后的日亏损基准**：新的一天必须重新写 `day_start_equity`，昨日亏损不影响今日。（Task 11 `test_daily_loss_limit_and_reset_on_new_utc_day`）
5. **分类器任何异常**（HTTP 错误、超时、非法 JSON、预算耗尽、输出中有未知符号）都不能让新闻管道崩溃，必须退化为关键词兜底或丢弃未知符号。（Task 9 `test_http_error_falls_back_to_keyword`、`test_timeout_falls_back_to_keyword`、`test_malformed_json_falls_back_to_keyword`、`test_unknown_symbols_dropped`）

---

## 文件结构

```
pyproject.toml, .gitignore, .env.example, README.md
src/ai_trader/
  __init__.py, settings.py, models.py, bus.py, logging_setup.py, cli.py, app.py
  exchange/__init__.py
  exchange/binance/__init__.py, errors.py, filters.py, parsers.py, rest.py, ws.py
  data/__init__.py, market_state.py, market_feed.py
  data/news/__init__.py, base.py, rss.py, x_api.py, poller.py
  analysis/__init__.py, forward_returns.py
  analysis/sentiment/__init__.py, base.py, keyword.py, deepseek.py
  analysis/detectors/__init__.py, base.py, funding_extreme.py, liquidation_burst.py, news_sentiment.py
  strategy/__init__.py, aggregator.py, autotune.py
  risk/__init__.py, engine.py, kill_switch.py
  execution/__init__.py, broker.py, paper.py, binance.py, service.py
  storage/__init__.py, db.py
tests/
  conftest.py
  fixtures/binance/*.json, fixtures/news/*
  unit/test_settings.py, test_models.py, test_bus.py, test_filters.py, test_parsers.py, test_rest.py, test_ws.py,
       test_store.py, test_market_feed.py, test_detectors.py, test_news_sources.py, test_sentiment.py,
       test_aggregator.py, test_risk.py, test_paper_broker.py, test_binance_broker.py, test_execution.py,
       test_forward_returns.py, test_app.py, test_cli.py, test_autotune.py
  integration/test_testnet.py
```

---

### Task 1: 项目骨架、配置与日志

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `src/ai_trader/__init__.py`, `src/ai_trader/settings.py`, `src/ai_trader/logging_setup.py`, `src/ai_trader/cli.py`（仅 `version` 子命令）
- Test: `tests/conftest.py`（先空）, `tests/unit/test_settings.py`

**Interfaces:**
- Produces: `Settings`, `RiskLimits`, `StrategyConfig`, `DetectorConfig`, `NewsConfig`, `ClaudeConfig`（字段与默认值见设计稿 5.1）；`Settings.effective_rest_url`、`Settings.effective_ws_url` 属性；常量 `TESTNET_REST`、`TESTNET_WS`、`MAINNET_REST`、`MAINNET_WS`；`configure_logging(level: str, json_format: bool) -> None`；`ai_trader.__version__ = "2.0.0a0"`。

- [ ] **Step 1: 初始化 uv 项目**

```bash
uv init --lib --name ai_trader --python 3.12 .
uv add httpx websockets "pydantic>=2.7" pydantic-settings anthropic aiosqlite typer feedparser
uv add --group dev pytest pytest-asyncio respx ruff mypy
```
在 `pyproject.toml` 加：`[project.scripts] ai-trader = "ai_trader.cli:app"`；`[tool.pytest.ini_options] testpaths=["tests"] asyncio_mode="auto" markers=["integration: 需要测试网 key","network: 需要公网"]`；`[tool.ruff] line-length=110 target-version="py312"`。`.gitignore` 含 `.venv/ data/ .env *.db __pycache__/ .pytest_cache/ .ruff_cache/ .mypy_cache/ *.egg-info/`。

- [ ] **Step 2: 写失败测试**

```python
# tests/unit/test_settings.py
from decimal import Decimal
from ai_trader.settings import Settings

def test_defaults_point_to_testnet(monkeypatch):
    monkeypatch.delenv("BINANCE_TESTNET", raising=False)
    s = Settings(_env_file=None)
    assert s.binance_testnet is True
    assert s.effective_rest_url == "https://testnet.binancefuture.com"
    assert s.effective_ws_url == "wss://stream.binancefuture.com"
    assert s.mode == "paper"
    assert s.symbols == ["BTCUSDT", "ETHUSDT"]
    assert s.risk.max_order_notional_usdt == Decimal("200")
    assert s.claude.model == "claude-opus-5"

def test_mainnet_urls_when_testnet_false():
    s = Settings(_env_file=None, binance_testnet=False)
    assert s.effective_rest_url == "https://fapi.binance.com"
    assert s.effective_ws_url == "wss://fstream.binance.com"

def test_nested_env_override(monkeypatch):
    monkeypatch.setenv("RISK__MAX_LEVERAGE", "5")
    monkeypatch.setenv("NEWS__X_DAILY_READ_BUDGET", "100")
    s = Settings(_env_file=None)
    assert s.risk.max_leverage == 5 and s.news.x_daily_read_budget == 100

def test_secrets_not_in_repr(monkeypatch):
    monkeypatch.setenv("BINANCE_API_SECRET", "topsecret")
    s = Settings(_env_file=None)
    assert "topsecret" not in repr(s) and "topsecret" not in str(s.model_dump())
```

- [ ] **Step 3: 运行确认失败** — `uv run pytest tests/unit/test_settings.py -q` → ImportError。

- [ ] **Step 4: 实现 `settings.py`、`logging_setup.py`、`cli.py`**

`settings.py`：按设计稿 5.1 定义五个 `BaseModel` 与 `Settings(BaseSettings)`；`model_config = SettingsConfigDict(env_file=".env", env_nested_delimiter="__", extra="ignore")`。`logging_setup.configure_logging(level, json_format)`：`json_format=True` 时用自定义 `logging.Formatter` 输出单行 JSON（字段 `ts,level,logger,msg`）。`cli.py`：`app = typer.Typer(no_args_is_help=True)`，`@app.command() def version()` 打印 `__version__`。

- [ ] **Step 5: 运行通过** — `uv run pytest -q && uv run ruff check . && uv run ai-trader version` → 全绿，输出 `2.0.0a0`。

- [ ] **Step 6: 提交** — `git add -A && git commit -m "chore: project skeleton with settings, logging and CLI entrypoint"`

---

### Task 2: 领域模型与事件总线

**Files:**
- Create: `src/ai_trader/models.py`, `src/ai_trader/bus.py`
- Test: `tests/unit/test_models.py`, `tests/unit/test_bus.py`

**Interfaces:**
- Produces: 设计稿 5.2 全部枚举、模型、事件与工具函数；5.3 `EventBus`。

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/test_models.py
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest
from ai_trader.models import (Direction, Liquidation, Position, PositionSide, RiskVerdict, Side, Signal,
                              new_client_order_id)

def test_signal_signed_strength():
    now = datetime.now(timezone.utc)
    s = Signal(id="a", detector="d", symbol="BTCUSDT", direction=Direction.BEARISH, strength=0.8,
               created_at=now, expires_at=now + timedelta(hours=1), ref_price=Decimal("80000"), rationale="x")
    assert s.signed_strength == -0.8

def test_client_order_id_matches_binance_pattern():
    cid = new_client_order_id()
    assert len(cid) == 32 and re.fullmatch(r"[\.A-Z\:/a-z0-9_-]{1,36}", cid) and cid.startswith("ait-")

def test_liquidation_and_position_notional():
    liq = Liquidation(symbol="BTCUSDT", side=Side.SELL, price=Decimal("80000"), qty=Decimal("0.5"),
                      event_time=datetime.now(timezone.utc))
    assert liq.notional == Decimal("40000")
    p = Position(symbol="BTCUSDT", side=PositionSide.LONG, quantity=Decimal("0.002"), entry_price=Decimal("1"),
                 mark_price=Decimal("80000"), unrealized_pnl=Decimal("0"), leverage=2, liquidation_price=None)
    assert p.notional == Decimal("160")

def test_models_are_frozen():
    v = RiskVerdict(approved=True)
    with pytest.raises(Exception):
        v.approved = False  # type: ignore[misc]
```

```python
# tests/unit/test_bus.py
import asyncio
from ai_trader.bus import EventBus

class A: ...
class B(A): ...

async def _append(lst, e): lst.append(e)

async def test_delivers_by_isinstance():
    bus = EventBus(); got = []
    bus.subscribe(A, lambda e: _append(got, e))
    await bus.start(); bus.publish(B()); await bus.drain(); await bus.stop()
    assert len(got) == 1 and isinstance(got[0], B)

async def test_slow_handler_does_not_block_fast_one():
    bus = EventBus(); fast = []
    async def slow(e): await asyncio.sleep(0.5)
    bus.subscribe(A, slow); bus.subscribe(A, lambda e: _append(fast, e))
    await bus.start(); bus.publish(A()); await asyncio.sleep(0.05)
    assert len(fast) == 1
    await bus.stop()

async def test_handler_exception_is_isolated():
    bus = EventBus(); ok = []
    async def bad(e): raise RuntimeError("boom")
    bus.subscribe(A, bad); bus.subscribe(A, lambda e: _append(ok, e))
    await bus.start(); bus.publish(A()); await bus.drain(); await bus.stop()
    assert len(ok) == 1

async def test_overflow_drops_oldest_and_counts():
    bus = EventBus()
    async def never(e): await asyncio.sleep(10)
    bus.subscribe(A, never, maxsize=2)
    for _ in range(5): bus.publish(A())
    assert sum(bus.dropped.values()) == 3
```

- [ ] **Step 2: 运行确认失败** — `uv run pytest tests/unit/test_models.py tests/unit/test_bus.py -q` → ImportError。

- [ ] **Step 3: 实现 `models.py` 与 `bus.py`**

`models.py`：`class _Frozen(BaseModel): model_config = ConfigDict(frozen=True)`，所有模型继承。`bus.py`：`subscribe` 记录 `(event_type, handler, asyncio.Queue(maxsize))`；`publish` 对每个 `isinstance(event, event_type)` 的订阅 `put_nowait`，`QueueFull` 时 `get_nowait()` 丢最旧再放入并 `dropped[key] += 1`；`start` 为每个订阅起 worker（`try/except Exception: log.exception`）；`drain` 轮询直到所有队列 `empty()` 且 in-flight 计数为 0 或超时。

- [ ] **Step 4: 运行通过** — `uv run pytest -q && uv run ruff check .`
- [ ] **Step 5: 提交** — `git add -A && git commit -m "feat: domain models and typed event bus"`

---

### Task 3: 币安合约 REST 客户端、过滤器与解析器

**Files:**
- Create: `src/ai_trader/exchange/__init__.py`, `src/ai_trader/exchange/binance/__init__.py`, `errors.py`, `filters.py`, `parsers.py`（REST 部分）, `rest.py`
- Create fixtures: `tests/fixtures/binance/exchange_info.json`（BTCUSDT：tickSize 0.10、stepSize 0.001、minQty 0.001、maxQty 1000、MIN_NOTIONAL notional 100、pricePrecision 2、quantityPrecision 3；ETHUSDT：tickSize 0.01、stepSize 0.001、notional 20；再加一个 `status: "SETTLING"` 的 symbol 应被过滤掉）、`premium_index.json`（实录：markPrice 80876.26033380、lastFundingRate 0.00010000、nextFundingTime 1793232000000）、`order_response.json`（币安文档样例，`status: "NEW"`）、`account_v2.json`、`position_risk_v2.json`（BTCUSDT positionAmt "-0.002"，ETHUSDT "0.000"）
- Test: `tests/unit/test_filters.py`, `tests/unit/test_rest.py`, `tests/unit/test_parsers.py`（REST 解析部分）
- Modify: `src/ai_trader/cli.py`（新增 `probe`）

**Interfaces:**
- Consumes: Task 2 模型。
- Produces: 设计稿 5.4 `errors.py`、`SymbolFilters`、`ExchangeInfo`、REST 解析函数、`BinanceFuturesRest` 全部方法（含可替换属性 `_retry_sleep`）；CLI `probe`。

- [ ] **Step 1: 写失败测试（过滤器）**

```python
# tests/unit/test_filters.py
from decimal import Decimal
import pytest
from ai_trader.exchange.binance.errors import FilterViolation
from ai_trader.exchange.binance.filters import SymbolFilters
from ai_trader.models import OrderRequest, OrderType, Side

F = SymbolFilters("BTCUSDT", Decimal("0.10"), Decimal("0.001"), Decimal("0.001"), Decimal("1000"), Decimal("100"), 2, 3)

def test_round_price_floors_to_tick(): assert F.round_price(Decimal("80876.26")) == Decimal("80876.20")
def test_round_qty_floors_to_step(): assert F.round_qty(Decimal("0.0029")) == Decimal("0.002")
def test_qty_for_notional(): assert F.qty_for_notional(Decimal("200"), Decimal("80000")) == Decimal("0.002")
def test_qty_for_notional_below_min_notional_raises():
    with pytest.raises(FilterViolation): F.qty_for_notional(Decimal("50"), Decimal("80000"))
def test_qty_for_notional_below_min_qty_raises():
    with pytest.raises(FilterViolation): F.qty_for_notional(Decimal("150"), Decimal("200000"))
def test_validate_rejects_unaligned_qty():
    req = OrderRequest(symbol="BTCUSDT", side=Side.BUY, type=OrderType.MARKET, quantity=Decimal("0.0015"), client_order_id="ait-x")
    with pytest.raises(FilterViolation): F.validate(req)
def test_validate_allows_close_position_without_qty():
    req = OrderRequest(symbol="BTCUSDT", side=Side.SELL, type=OrderType.STOP_MARKET, stop_price=Decimal("79000.0"),
                       close_position=True, client_order_id="ait-y")
    F.validate(req)
```

- [ ] **Step 2: 写失败测试（REST）**

```python
# tests/unit/test_rest.py
import json, pathlib
from decimal import Decimal
import httpx, pytest, respx
from ai_trader.exchange.binance.errors import BinanceAPIError, BinanceConnectionError, BinanceRateLimitError
from ai_trader.exchange.binance.rest import BinanceFuturesRest
from ai_trader.models import OrderRequest, OrderStatus, OrderType, Side

FX = pathlib.Path(__file__).parents[1] / "fixtures" / "binance"
BASE = "https://testnet.binancefuture.com"
def fx(name): return json.loads((FX / name).read_text())
async def _noop(_s): return None

def test_sign_matches_binance_doc_vector():
    c = BinanceFuturesRest(BASE, "k", "NhqPtmdSJYdKjVHjA7PZj4Mge3R5YNiP1e3UZjInClVN65XAbvqqM6A7H5fATj0j")
    q = "symbol=LTCBTC&side=BUY&type=LIMIT&timeInForce=GTC&quantity=1&price=0.1&recvWindow=5000&timestamp=1499827319559"
    assert c.sign(q) == "c8db56825ae71d6d79447849e617115f4a920fa2acdcab2b053c4b2838bd6b71"

@respx.mock
async def test_exchange_info_filters_non_trading():
    respx.get(f"{BASE}/fapi/v1/exchangeInfo").mock(return_value=httpx.Response(200, json=fx("exchange_info.json")))
    info = await BinanceFuturesRest(BASE).exchange_info()
    assert set(info.symbols) == {"BTCUSDT", "ETHUSDT"}
    assert info.filters_for("BTCUSDT").min_notional == Decimal("100")

@respx.mock
async def test_place_order_sends_signed_params_and_header():
    route = respx.post(f"{BASE}/fapi/v1/order").mock(return_value=httpx.Response(200, json=fx("order_response.json")))
    c = BinanceFuturesRest(BASE, "KEY", "SECRET", clock=lambda: 1700000000.0)
    req = OrderRequest(symbol="BTCUSDT", side=Side.BUY, type=OrderType.MARKET, quantity=Decimal("0.002"), client_order_id="ait-abc")
    res = await c.place_order(req)
    sent = route.calls.last.request
    assert sent.headers["X-MBX-APIKEY"] == "KEY"
    body = sent.content.decode()
    assert "newClientOrderId=ait-abc" in body and "quantity=0.002" in body and "timestamp=1700000000000" in body
    assert body.split("&")[-1].startswith("signature=")
    assert res.status == OrderStatus.NEW and res.client_order_id == fx("order_response.json")["clientOrderId"]

@respx.mock
async def test_api_error_raises_with_code():
    respx.get(f"{BASE}/fapi/v2/account").mock(return_value=httpx.Response(400, json={"code": -2015, "msg": "Invalid API-key"}))
    with pytest.raises(BinanceAPIError) as ei: await BinanceFuturesRest(BASE, "k", "s").account()
    assert ei.value.code == -2015 and ei.value.status == 400

@respx.mock
async def test_rate_limit_raises_specific_error():
    respx.get(f"{BASE}/fapi/v1/ping").mock(return_value=httpx.Response(429, headers={"Retry-After": "7"}, json={"code": -1003, "msg": "x"}))
    c = BinanceFuturesRest(BASE); c._retry_sleep = _noop
    with pytest.raises(BinanceRateLimitError) as ei: await c.ping()
    assert ei.value.retry_after_s == 7

@respx.mock
async def test_get_retries_on_connect_error_then_succeeds():
    route = respx.get(f"{BASE}/fapi/v1/time")
    route.side_effect = [httpx.ConnectError("x"), httpx.Response(200, json={"serverTime": 1700000001000})]
    c = BinanceFuturesRest(BASE); c._retry_sleep = _noop
    assert await c.server_time() == 1700000001000 and route.call_count == 2

@respx.mock
async def test_post_is_not_retried():
    route = respx.post(f"{BASE}/fapi/v1/order").mock(side_effect=httpx.ConnectError("x"))
    with pytest.raises(BinanceConnectionError):
        await BinanceFuturesRest(BASE, "k", "s").place_order(OrderRequest(symbol="BTCUSDT", side=Side.BUY, type=OrderType.MARKET, quantity=Decimal("0.002"), client_order_id="ait-1"))
    assert route.call_count == 1

@respx.mock
async def test_set_margin_type_swallows_4046():
    respx.post(f"{BASE}/fapi/v1/marginType").mock(return_value=httpx.Response(400, json={"code": -4046, "msg": "No need to change margin type."}))
    await BinanceFuturesRest(BASE, "k", "s").set_margin_type("BTCUSDT", "ISOLATED")

@respx.mock
async def test_position_risk_parses_sides():
    respx.get(f"{BASE}/fapi/v2/positionRisk").mock(return_value=httpx.Response(200, json=fx("position_risk_v2.json")))
    ps = await BinanceFuturesRest(BASE, "k", "s").position_risk()
    by = {p.symbol: p for p in ps}
    assert by["BTCUSDT"].side.value == "SHORT" and by["BTCUSDT"].quantity == Decimal("0.002") and by["ETHUSDT"].side.value == "FLAT"
```

- [ ] **Step 3: 运行确认失败** — `uv run pytest tests/unit/test_filters.py tests/unit/test_rest.py -q`

- [ ] **Step 4: 实现 `errors.py`、`filters.py`、`parsers.py`（REST 函数）、`rest.py`**

签名按设计稿 5.4。`rest.py` 内部：`_request(method, path, params, *, signed: bool, retry: bool)`；`_retry_sleep = asyncio.sleep` 作为可替换属性；签名请求把参数编码为 `urlencode(params)` 字串，再拼 `&signature=`，GET/DELETE 放查询串，POST/PUT 放 body（`application/x-www-form-urlencoded`）。429 不重试、直接抛。

- [ ] **Step 5: 实现 CLI `probe`**

`ai-trader probe`：构造 `Settings()` 与 REST 客户端；打印 ping 耗时、`server_time` 与本地偏移、`exchange_info` 合约数、各 `settings.symbols` 的标记价与年化资金费（`rate*3*365`）；若有 key，打印 `account().total_wallet_balance`；失败打印错误类型与 `code/msg`，退出码 1。

- [ ] **Step 6: 运行通过并实打测试网** — `uv run pytest -q && uv run ruff check . && uv run ai-trader probe` → 测试全绿；probe 打印约 743 个合约和 BTCUSDT 标记价。
- [ ] **Step 7: 提交** — `git add -A && git commit -m "feat: Binance USDT-M futures REST client, symbol filters and probe command"`

---

### Task 4: WebSocket 客户端与流消息解析

**Files:**
- Create: `src/ai_trader/exchange/binance/ws.py`；补全 `parsers.py` 的 WS 函数
- Create fixtures: `tests/fixtures/binance/ws_mark_price.json`（实录：`{"e":"markPriceUpdate","E":1793212382000,"s":"BTCUSDT","p":"80874.42344203","P":"80840.72999215","i":"80839.82913043","r":"0.00010000","T":1793232000000}`）、`ws_kline.json`、`ws_force_order.json`（文档样例，`o.S="SELL"`、`o.p="9910"`、`o.q="0.014"`）、`ws_order_trade_update_fill.json`（`x="TRADE"`、`X="FILLED"`、`l="0.002"`、`L="80000"`、`rp="1.5"`、`n="0.064"`、`c="ait-abc"`、`i=8886774`）、`ws_account_update.json`（`a.P[0]`：`s="BTCUSDT"`、`pa="0.002"`、`ep="80000"`、`up="1.2"`；`a.B[0]`：`a="USDT"`、`wb="10001.2"`、`cw="9000"`）
- Test: `tests/unit/test_parsers.py`（WS 部分）, `tests/unit/test_ws.py`

**Interfaces:**
- Produces: `market_stream_url`、`user_stream_url`、`BinanceFuturesWS`（设计稿 5.4）；`parse_mark_price`、`parse_kline`、`parse_force_order`、`parse_order_trade_update`、`parse_account_update`。

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/test_parsers.py（追加）
def test_parse_mark_price_fixture():
    mp = parse_mark_price(fx("ws_mark_price.json"))
    assert mp.symbol == "BTCUSDT" and mp.mark_price == Decimal("80874.42344203") and mp.funding_rate == Decimal("0.00010000")
    assert mp.next_funding_time.tzinfo is not None and int(mp.next_funding_time.timestamp()) == 1793232000

def test_parse_force_order_sell_means_long_liquidated():
    liq = parse_force_order(fx("ws_force_order.json"))
    assert liq.side == Side.SELL and liq.notional == Decimal("9910") * Decimal("0.014")

def test_parse_order_trade_update_produces_fill():
    res, fill = parse_order_trade_update(fx("ws_order_trade_update_fill.json"))
    assert res.status == OrderStatus.FILLED and res.client_order_id == "ait-abc" and res.order_id == 8886774
    assert fill is not None and fill.qty == Decimal("0.002") and fill.price == Decimal("80000") and fill.realized_pnl == Decimal("1.5")

def test_parse_order_trade_update_new_has_no_fill():
    d = fx("ws_order_trade_update_fill.json"); d["o"]["x"] = "NEW"; d["o"]["X"] = "NEW"; d["o"]["l"] = "0"
    _, fill = parse_order_trade_update(d); assert fill is None

def test_parse_account_update_positions_and_balance():
    upd = parse_account_update(fx("ws_account_update.json"))
    assert upd.state.total_wallet_balance == Decimal("10001.2") and upd.state.positions[0].side == PositionSide.LONG
```

```python
# tests/unit/test_ws.py
import asyncio, json
import websockets
from ai_trader.exchange.binance.ws import BinanceFuturesWS, market_stream_url, user_stream_url

def test_urls():
    assert market_stream_url("wss://x", ["a@b", "c@d"]) == "wss://x/stream?streams=a@b/c@d"
    assert user_stream_url("wss://x", "LK") == "wss://x/ws/LK"

async def test_receives_unwraps_and_reconnects():
    conns = 0
    async def server(ws):
        nonlocal conns; conns += 1
        await ws.send(json.dumps({"stream": "s", "data": {"e": "ping", "n": conns}}))
        await ws.close()
    async with websockets.serve(server, "127.0.0.1", 0) as srv:
        port = srv.sockets[0].getsockname()[1]
        got = []
        async def h(m): got.append(m)
        ws = BinanceFuturesWS(f"ws://127.0.0.1:{port}", h, backoff_s=(0.05,))
        task = asyncio.create_task(ws.run())
        for _ in range(100):
            if len(got) >= 2: break
            await asyncio.sleep(0.05)
        await ws.stop(); await task
    assert [m["n"] for m in got[:2]] == [1, 2] and ws.reconnects >= 1 and ws.last_message_at is not None
```

- [ ] **Step 2: 运行确认失败** — `uv run pytest tests/unit/test_ws.py tests/unit/test_parsers.py -q`
- [ ] **Step 3: 实现** — `ws.py` 按设计稿；`run()` 外层 `while not self._stopped`，内层 `async for raw in conn`；每次重连成功把退避索引归零；`stop()` 设标志并关闭当前连接。
- [ ] **Step 4: 运行通过** — `uv run pytest -q && uv run ruff check .`
- [ ] **Step 5: 提交** — `git add -A && git commit -m "feat: Binance futures WebSocket client and stream parsers"`

---

### Task 5: SQLite 存储层

**Files:**
- Create: `src/ai_trader/storage/__init__.py`, `src/ai_trader/storage/db.py`
- Modify: `tests/conftest.py`（加入共享构造函数）
- Test: `tests/unit/test_store.py`

**Interfaces:**
- Consumes: Task 2 模型。
- Produces: `Store` 与 `EffectivenessRow`（设计稿 5.10 全部方法）。`EffectivenessRow = NamedTuple(detector: str, horizon_s: int, n: int, mean_ret: float, hit_rate: float)`。
- `tests/conftest.py` 产出：`T0 = datetime(2026, 10, 29, tzinfo=timezone.utc)`；`make_news(id, title="t", text="x", source="rss")`、`make_signal(id, *, detector="funding_extreme", symbol="BTCUSDT", direction=Direction.BULLISH, strength=0.7, created_at=T0, expires_at=T0+1h, ref_price=Decimal("80000"))`、`make_fill(cid, *, realized_pnl=Decimal("0"), event_time=T0, symbol="BTCUSDT")`、`make_order_record(cid, *, role, status, symbol="BTCUSDT")`、`make_mark_price(*, symbol="BTCUSDT", mark=Decimal("80000"), funding_rate=Decimal("0.0001"), next_funding_time=T0+8h)`、`make_liq(side, *, price, qty, symbol="BTCUSDT")`、`make_position(side, qty, mark, *, symbol="BTCUSDT", entry=None)`、`make_account(*, wallet, positions)`、`make_decision(*, symbol="BTCUSDT", side=Side.BUY, intent=Intent.OPEN, notional=Decimal("100"))`、`_append(lst, e)`、`fx(name)`（读 `tests/fixtures/binance/`）。后续任务按此名字使用。

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/test_store.py
async def test_insert_news_dedupes(tmp_path):
    st = Store(tmp_path / "t.db"); await st.open()
    item = make_news("n1")
    assert await st.insert_news(item) is True and await st.insert_news(item) is False and await st.news_exists("n1")

async def test_signals_forward_returns_and_effectiveness(tmp_path):
    st = Store(tmp_path / "t.db"); await st.open()
    await st.insert_signal(make_signal("s1", detector="funding_extreme", created_at=T0))
    assert [x.id for x in await st.signals_missing_forward_return(600, before=T0 + timedelta(seconds=601))] == ["s1"]
    await st.insert_forward_return("s1", 600, 0.004)
    assert await st.signals_missing_forward_return(600, before=T0 + timedelta(hours=1)) == []
    rows = await st.effectiveness()
    assert rows[0].detector == "funding_extreme" and rows[0].n == 1 and rows[0].hit_rate == 1.0

async def test_mark_at_uses_nearest_within_tolerance(tmp_path):
    st = Store(tmp_path / "t.db"); await st.open()
    await st.insert_mark_sample("BTCUSDT", T0, Decimal("80000"))
    await st.insert_mark_sample("BTCUSDT", T0 + timedelta(seconds=30), Decimal("80100"))
    assert await st.mark_at("BTCUSDT", T0 + timedelta(seconds=25)) == Decimal("80100")
    assert await st.mark_at("BTCUSDT", T0 + timedelta(hours=1)) is None

async def test_realized_pnl_and_consecutive_losses(tmp_path):
    st = Store(tmp_path / "t.db"); await st.open()
    for i, pnl in enumerate(["5", "-1", "0", "-2", "-3"]):
        await st.insert_fill(make_fill(f"c{i}", realized_pnl=Decimal(pnl), event_time=T0 + timedelta(minutes=i)))
    assert await st.realized_pnl_since(T0 + timedelta(minutes=1)) == Decimal("-6")
    assert await st.consecutive_losses() == 3   # 0 被过滤后 -3,-2,-1 连续三笔

async def test_kv_and_orders_roundtrip(tmp_path):
    st = Store(tmp_path / "t.db"); await st.open()
    await st.set_kv("kill_switch", "1"); assert await st.get_kv("kill_switch") == "1"
    await st.upsert_order(make_order_record("ait-1", role=OrderRole.STOP_LOSS, status=OrderStatus.NEW))
    assert (await st.get_order("ait-1")).role == OrderRole.STOP_LOSS
    assert [o.client_order_id for o in await st.open_protective_orders("BTCUSDT")] == ["ait-1"]
    await st.update_order_status("ait-1", OrderStatus.FILLED, Decimal("0.002"), Decimal("79000"), 99)
    assert await st.open_protective_orders("BTCUSDT") == []
```

- [ ] **Step 2: 运行确认失败** — `uv run pytest tests/unit/test_store.py -q`
- [ ] **Step 3: 实现 `db.py`** — `aiosqlite`；datetime 存 ISO8601 UTC 字串，Decimal 存 TEXT；`consecutive_losses`：`SELECT realized_pnl FROM fills WHERE realized_pnl != '0' ORDER BY event_time DESC`，Python 中数前缀负数；`open_protective_orders`：`role IN ('stop_loss','take_profit') AND status IN ('NEW','PARTIALLY_FILLED')`；`effectiveness`：`GROUP BY detector, horizon_s`，`hit_rate = AVG(ret > 0)`。
- [ ] **Step 4: 运行通过** — `uv run pytest -q && uv run ruff check .`
- [ ] **Step 5: 提交** — `git add -A && git commit -m "feat: SQLite store for news, signals, orders, fills and forward returns"`

---

### Task 6: 行情接入、市场状态与陈旧监测

**Files:**
- Create: `src/ai_trader/data/__init__.py`, `market_state.py`, `market_feed.py`
- Test: `tests/unit/test_market_feed.py`

**Interfaces:**
- Consumes: `EventBus`、`Store`、`BinanceFuturesWS`、WS 解析函数。
- Produces: `MarketState(clock=time.monotonic)`、`build_stream_names`、`MarketFeed`、`StalenessWatchdog`、`MarkPriceSampler`（设计稿 5.5）。

- [ ] **Step 1: 写失败测试**

```python
def test_build_stream_names():
    assert build_stream_names(["BTCUSDT"]) == ["btcusdt@markPrice@1s", "btcusdt@kline_1m", "btcusdt@forceOrder"]

async def test_feed_handle_publishes_typed_events_and_updates_state():
    bus = EventBus(); state = MarketState(); got = []
    bus.subscribe(MarkPrice, lambda e: _append(got, e)); bus.subscribe(Liquidation, lambda e: _append(got, e))
    feed = MarketFeed(bus, state, "wss://x", ["BTCUSDT"])
    await bus.start(); await feed.handle(fx("ws_mark_price.json")); await feed.handle(fx("ws_force_order.json"))
    await bus.drain(); await bus.stop()
    assert {type(e).__name__ for e in got} == {"MarkPrice", "Liquidation"}
    assert state.mark("BTCUSDT").mark_price == Decimal("80874.42344203")

async def test_watchdog_emits_stale_then_fresh():
    t = [0.0]; clock = lambda: t[0]
    bus = EventBus(); state = MarketState(clock=clock); events = []
    bus.subscribe(DataStale, lambda e: _append(events, e)); bus.subscribe(DataFresh, lambda e: _append(events, e))
    wd = StalenessWatchdog(bus, state, ["BTCUSDT"], max_age_s=10, check_interval_s=0.01, clock=clock)
    await bus.start(); task = asyncio.create_task(wd.run())
    state.update_mark(parse_mark_price(fx("ws_mark_price.json"))); t[0] = 5; await asyncio.sleep(0.05)
    assert wd.is_stale("BTCUSDT") is False
    t[0] = 20; await asyncio.sleep(0.05); await bus.drain()
    assert isinstance(events[-1], DataStale) and events[-1].age_s >= 10
    state.update_mark(parse_mark_price(fx("ws_mark_price.json"))); await asyncio.sleep(0.05); await bus.drain()
    assert isinstance(events[-1], DataFresh)
    await wd.stop(); await task; await bus.stop()

async def test_sampler_writes_at_most_once_per_interval(tmp_path):
    t = [0.0]; st = Store(tmp_path / "t.db"); await st.open(); bus = EventBus()
    MarkPriceSampler(bus, st, interval_s=10, clock=lambda: t[0]); await bus.start()
    for _ in range(3): bus.publish(make_mark_price())
    await bus.drain(); assert await st.count("mark_samples") == 1
    t[0] = 10; bus.publish(make_mark_price()); await bus.drain(); assert await st.count("mark_samples") == 2
```
（在 `Store` 增加测试辅助 `count(table: str) -> int`。）

- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现** — `StalenessWatchdog` 维持 `_stale: set[str]`，仅在状态切换时发事件，无数据视为陈旧（`age_s=float("inf")`）。`MarkPriceSampler(bus, store, interval_s=10, clock=time.monotonic)` 在构造时订阅。
- [ ] **Step 4: 运行通过** — `uv run pytest -q && uv run ruff check .`
- [ ] **Step 5: 提交** — `git add -A && git commit -m "feat: market feed, market state, staleness watchdog and mark price sampler"`

---

### Task 7: 行情探测器（资金费率极端、清算爆发）

**Files:**
- Create: `src/ai_trader/analysis/__init__.py`, `analysis/detectors/__init__.py`, `base.py`, `funding_extreme.py`, `liquidation_burst.py`
- Test: `tests/unit/test_detectors.py`

**Interfaces:**
- Produces: `Detector` Protocol、`DetectorRunner(bus, store, detectors)`、`FundingExtremeDetector(cfg: DetectorConfig, state: MarketState, *, clock=time.time)`、`LiquidationBurstDetector(cfg, state, *, clock=time.time)`（设计稿 5.6）。`name` 分别为 `"funding_extreme"`、`"liquidation_burst"`。

- [ ] **Step 1: 写失败测试**

```python
async def test_funding_extreme_bearish_once_per_period():
    det = FundingExtremeDetector(DetectorConfig(), MarketState(), clock=lambda: 0.0)
    mp = make_mark_price(funding_rate=Decimal("0.0005"))   # 年化 0.5475 ≥ 0.30 → BEARISH, strength = 0.5475/0.6
    sigs = await det.on_event(mp)
    assert len(sigs) == 1 and sigs[0].direction == Direction.BEARISH and abs(sigs[0].strength - 0.9125) < 1e-3
    assert sigs[0].expires_at == mp.next_funding_time and sigs[0].detector == "funding_extreme"
    assert await det.on_event(mp) == []

async def test_funding_negative_is_bullish_and_below_threshold_silent():
    det = FundingExtremeDetector(DetectorConfig(), MarketState(), clock=lambda: 0.0)
    assert (await det.on_event(make_mark_price(funding_rate=Decimal("-0.0004"))))[0].direction == Direction.BULLISH
    assert await det.on_event(make_mark_price(funding_rate=Decimal("0.0001"), next_funding_time=T0 + timedelta(hours=16))) == []

async def test_liquidation_burst_bullish_on_long_liquidations_with_cooldown():
    t = [0.0]
    det = LiquidationBurstDetector(DetectorConfig(liquidation_notional_threshold_usdt=Decimal("1000")), MarketState(), clock=lambda: t[0])
    assert await det.on_event(make_liq(Side.SELL, price=Decimal("100"), qty=Decimal("6"))) == []       # 600 < 1000
    sigs = await det.on_event(make_liq(Side.SELL, price=Decimal("100"), qty=Decimal("6")))             # 1200 ≥ 1000
    assert sigs[0].direction == Direction.BULLISH and abs(sigs[0].strength - 0.6) < 1e-9
    assert await det.on_event(make_liq(Side.SELL, price=Decimal("100"), qty=Decimal("50"))) == []      # 冷却中
    t[0] = 1000
    assert (await det.on_event(make_liq(Side.BUY, price=Decimal("100"), qty=Decimal("20"))))[0].direction == Direction.BEARISH

async def test_runner_persists_then_publishes(tmp_path):
    class Fake:
        name = "fake"; subscribes_to = (MarkPrice,)
        async def on_event(self, e): return [make_signal("z", detector="fake")]
    st = Store(tmp_path / "t.db"); await st.open(); bus = EventBus(); got = []
    bus.subscribe(Signal, lambda e: _append(got, e)); DetectorRunner(bus, st, [Fake()])
    await bus.start(); bus.publish(make_mark_price()); await bus.drain(); await bus.stop()
    assert len(got) == 1 and (await st.recent_signals(5))[0].id == "z"
```

- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现** — `ref_price` 取 `state.mark(symbol).mark_price`，无则用事件自身价格（清算用 `price`，标记价用 `mark_price`）。`DetectorRunner` 在构造时为每个探测器的每个 `subscribes_to` 类型订阅。
- [ ] **Step 4: 运行通过** — `uv run pytest -q && uv run ruff check .`
- [ ] **Step 5: 提交** — `git add -A && git commit -m "feat: funding-extreme and liquidation-burst detectors with runner"`

---

### Task 8: 新闻源（RSS、X API）与轮询器

**Files:**
- Create: `src/ai_trader/data/news/__init__.py`, `base.py`, `rss.py`, `x_api.py`, `poller.py`
- Create fixtures: `tests/fixtures/news/sample.rss`（2 条 entry，含 `published`）、`tests/fixtures/news/x_search.json`（`data` 2 条含 `id,text,author_id,created_at`，`includes.users` 对应 `id,username`，`meta.newest_id`）
- Test: `tests/unit/test_news_sources.py`

**Interfaces:**
- Produces: `NewsSource` Protocol、`DailyBudget(limit, clock=time.time)`（`try_consume(n=1) -> bool`、`refund(n)`、`remaining`）、`RssSource`、`XSearchSource`（属性 `next_allowed_at: float`）、`NewsPoller`（设计稿 5.5）。

- [ ] **Step 1: 写失败测试**

```python
@respx.mock
async def test_rss_source_parses_entries():
    respx.get("https://feed.example/rss").mock(return_value=httpx.Response(200, content=(FXN / "sample.rss").read_bytes()))
    items = await RssSource("coindesk", "https://feed.example/rss", httpx.AsyncClient()).fetch()
    assert len(items) == 2 and items[0].source == "coindesk" and items[0].published_at.tzinfo is not None and items[0].id

@respx.mock
async def test_x_source_query_params_since_id_and_author():
    route = respx.get("https://api.x.com/2/tweets/search/recent").mock(return_value=httpx.Response(200, json=fxn("x_search.json")))
    src = XSearchSource("TOKEN", "from:binance", httpx.AsyncClient(), DailyBudget(100), max_results=10)
    items = await src.fetch()
    q = dict(route.calls.last.request.url.params)
    assert q["query"] == "from:binance" and q["max_results"] == "10" and "since_id" not in q
    assert route.calls.last.request.headers["Authorization"] == "Bearer TOKEN"
    assert items[0].id.startswith("x:") and items[0].author == fxn("x_search.json")["includes"]["users"][0]["username"]
    await src.fetch()
    assert dict(route.calls.last.request.url.params)["since_id"] == fxn("x_search.json")["meta"]["newest_id"]

@respx.mock
async def test_x_source_respects_daily_budget():
    route = respx.get("https://api.x.com/2/tweets/search/recent").mock(return_value=httpx.Response(200, json=fxn("x_search.json")))
    src = XSearchSource("T", "q", httpx.AsyncClient(), DailyBudget(1), max_results=10)
    assert await src.fetch() == [] and route.call_count == 0

def test_daily_budget_resets_on_utc_day_change():
    t = [1_700_000_000.0]; b = DailyBudget(2, clock=lambda: t[0])
    assert b.try_consume(2) and not b.try_consume(1)
    t[0] += 86400; assert b.try_consume(1)

@respx.mock
async def test_x_source_429_backs_off():
    respx.get("https://api.x.com/2/tweets/search/recent").mock(return_value=httpx.Response(429, headers={"x-rate-limit-reset": str(int(time.time()) + 900)}))
    src = XSearchSource("T", "q", httpx.AsyncClient(), DailyBudget(100))
    assert await src.fetch() == [] and src.next_allowed_at > time.time() + 800

async def test_poller_dedupes_and_publishes(tmp_path):
    class Src:
        name = "fake"
        async def fetch(self): return [make_news("same")]
    st = Store(tmp_path / "t.db"); await st.open(); bus = EventBus(); got = []
    bus.subscribe(NewsItem, lambda e: _append(got, e)); poller = NewsPoller(bus, st, [(Src(), 1)])
    await bus.start(); await poller.poll_once(); await poller.poll_once(); await bus.drain(); await bus.stop()
    assert len(got) == 1
```

- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现** — `XSearchSource` 请求前 `budget.try_consume(max_results)`，失败则不请求；成功后 `budget.refund(max_results - len(data))`。`NewsPoller.poll_once()` 对所有源各取一次；`run()` 为每个源起循环任务（按各自间隔），异常只记日志并继续。
- [ ] **Step 4: 运行通过** — `uv run pytest -q && uv run ruff check .`
- [ ] **Step 5: 提交** — `git add -A && git commit -m "feat: RSS and X search news sources with daily budget and poller"`

---

### Task 9: 情绪分类器（关键词、DeepSeek）与新闻情绪探测器

**Files:**
- Create: `src/ai_trader/analysis/sentiment/__init__.py`, `base.py`, `keyword.py`, `deepseek.py`; `src/ai_trader/analysis/detectors/news_sentiment.py`
- Modify: `src/ai_trader/settings.py`（`ClaudeConfig`/`claude` → `LLMConfig`/`llm`，新增 `deepseek_api_key: SecretStr | None = None`）、`tests/unit/test_settings.py`（`s.claude.model == "claude-opus-5"` 改为 `s.llm.model == "deepseek-chat"`）、`pyproject.toml`（`uv remove anthropic`）、`src/ai_trader/cli.py`（新增 `classify TEXT`）
- Test: `tests/unit/test_sentiment.py`

**Interfaces:**
- Consumes: `NewsItem`、`Sentiment`、`DailyBudget`（含 `refund`）、`Store`、`MarketState`、`httpx.AsyncClient`。
- Produces: `SentimentClassifier` Protocol（`name: str`，`async classify(item) -> Sentiment`）、`canonical_symbols(raw, universe) -> list[str]`、`KeywordClassifier(universe)`（`name="keyword"`）、`SentimentOutput(BaseModel)`（`direction: Literal["bullish","bearish","neutral"]`, `confidence: float`（0..1 夹紧）, `symbols: list[str]`, `horizon: Literal["minutes","hours","days"]`, `rationale: str`）、`DeepSeekClassifier(http: httpx.AsyncClient, api_key: str, universe: Sequence[str], *, model: str = "deepseek-chat", base_url: str = "https://api.deepseek.com", fallback: SentimentClassifier, budget: DailyBudget, max_text_chars: int = 4000, timeout_s: float = 30.0)`（`name = model`）、`NewsSentimentDetector(classifier, universe, store, state, cfg: DetectorConfig | None = None, *, min_confidence: float | None = None)`（`name="news_sentiment"`，`subscribes_to=(NewsItem,)`；阈值在每次调用时读取：`min_confidence` 传了就用它，否则读 `cfg.news_min_confidence`）。
- `LLMConfig`：`enabled: bool = True`、`provider: Literal["deepseek","none"] = "deepseek"`、`model: str = "deepseek-chat"`、`base_url: str = "https://api.deepseek.com"`、`daily_call_budget: int = 500`、`max_text_chars: int = 4000`、`timeout_s: float = 30.0`。

- [ ] **Step 1: 写失败测试**

```python
import json, httpx, respx
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
async def test_unknown_symbols_dropped():
    respx.post(DS).mock(return_value=ds_response({"direction": "bullish", "confidence": 0.9, "symbols": ["DOGE"], "horizon": "days", "rationale": "r"}))
    assert (await mk().classify(make_news("n"))).symbols == []

@respx.mock
async def test_malformed_json_falls_back_to_keyword():
    respx.post(DS).mock(return_value=ds_response(None, content="not json at all"))
    s = await mk().classify(make_news("n", title="Exchange hack", text=""))
    assert s.model == "keyword-fallback" and s.direction == Direction.BEARISH

@respx.mock
async def test_http_error_falls_back_to_keyword():
    respx.post(DS).mock(return_value=httpx.Response(500, json={"error": "boom"}))
    assert (await mk().classify(make_news("n", title="Exchange hack", text=""))).model == "keyword-fallback"

@respx.mock
async def test_timeout_falls_back_to_keyword():
    respx.post(DS).mock(side_effect=httpx.ReadTimeout("t"))
    assert (await mk().classify(make_news("n", title="Exchange hack", text=""))).model == "keyword-fallback"

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

async def test_news_detector_emits_per_symbol_and_filters_low_confidence(tmp_path):
    class C:
        name = "fake"
        def __init__(self, conf): self.conf = conf
        async def classify(self, item): return Sentiment(direction=Direction.BULLISH, confidence=self.conf, symbols=UNI, horizon=Horizon.HOURS, rationale="r", model="fake")
    st = Store(tmp_path / "t.db"); await st.open(); state = MarketState()
    for sym in UNI: state.update_mark(make_mark_price(symbol=sym))
    det = NewsSentimentDetector(C(0.7), UNI, st, state, min_confidence=0.6)
    sigs = await det.on_event(make_news("n1"))
    assert [s.symbol for s in sigs] == UNI and sigs[0].strength == 0.7 and sigs[0].expires_at - sigs[0].created_at == timedelta(hours=4) and sigs[0].detector == "news_sentiment"
    assert await NewsSentimentDetector(C(0.5), UNI, st, state, min_confidence=0.6).on_event(make_news("n2")) == []
    assert await st.count("sentiments") == 2

async def test_news_detector_reads_cfg_threshold_at_call_time(tmp_path):
    ...  # cfg = DetectorConfig(); det = NewsSentimentDetector(C(0.5), UNI, st, state, cfg) → [] ; cfg.news_min_confidence = 0.4 → 2 signals
```

- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现** — `deepseek.py`：`SYSTEM` 常量（角色：加密货币市场分析师；任务：判断新闻/帖子对永续合约价格的短期影响；列出符号 universe；置信度口径：官方/意外/与价格直接相关→高，传闻/营销/表情包→中性或低，市场整体消息归到 BTCUSDT；必须明确要求"以 JSON 对象回复，键为 direction/confidence/symbols/horizon/rationale"——DeepSeek 的 `json_object` 模式要求提示词里出现 "json"）。`classify` 流程：`budget.try_consume()` 失败→fallback；`POST {base_url}/chat/completions`，头 `Authorization: Bearer <key>`，体 `{"model", "temperature": 0, "max_tokens": 512, "response_format": {"type": "json_object"}, "messages": [system, user]}`，超时 `timeout_s`；非 2xx、`httpx.HTTPError`、`choices[0].message.content` 不是合法 JSON 或不通过 `SentimentOutput.model_validate_json` → `log.warning` 并 fallback（`model="keyword-fallback"`）；成功 → `canonical_symbols`，`Sentiment(model=self.model)`。user content 格式：`source / author / published_at / title / text(截断后加 "[truncated]")`。日志不得包含 key。`NewsSentimentDetector`：分类 → `store.insert_sentiment` → 每个命中符号一条 Signal（strength=confidence；horizon→过期 minutes 30 min / hours 4 h / days 24 h；`ref_price` 取 `state.mark(symbol)`，无则跳过该符号），NEUTRAL 或 confidence < 阈值时不发。CLI `classify TEXT`：有 `settings.deepseek_api_key` 且 `settings.llm.enabled` 用 DeepSeek，否则关键词，打印 JSON。
- [ ] **Step 4: 运行通过** — `uv run pytest -q && uv run ruff check . && uv run ai-trader classify "SEC approves spot ETH ETF options"`（本机 `.env` 有 DeepSeek key，应返回 `model: deepseek-chat`）
- [ ] **Step 5: 提交** — `git add -A && git commit -m "feat: keyword and DeepSeek sentiment classifiers with news sentiment detector"`

---

### Task 10: 信号聚合器

**Files:**
- Create: `src/ai_trader/strategy/__init__.py`, `src/ai_trader/strategy/aggregator.py`
- Test: `tests/unit/test_aggregator.py`

**Interfaces:**
- Produces: `SignalAggregator(bus, store, state, cfg: StrategyConfig, positions: Callable[[], Mapping[str, Position]], *, clock=time.time)`，方法 `score(symbol, now=None) -> float`、`async on_signal(s: Signal) -> Decision | None`、`async start()`（回填 `_last_decision_at` 并订阅 `Signal`）。

- [ ] **Step 1: 写失败测试**

```python
def make_agg(bus, st, positions=None, clock=None, **cfg):
    return SignalAggregator(bus, st, MarketState(), StrategyConfig(**cfg), positions=lambda: positions or {}, clock=clock or (lambda: T0.timestamp()))

async def test_score_weights_and_decay(bus, st):
    agg = make_agg(bus, st, signal_half_life_s=1800, entry_threshold=9.0)
    await agg.on_signal(make_signal("a", detector="news_sentiment", strength=0.5, created_at=T0, expires_at=T0 + timedelta(hours=4)))
    assert abs(agg.score("BTCUSDT", now=T0.timestamp()) - 0.5) < 1e-9
    assert abs(agg.score("BTCUSDT", now=T0.timestamp() + 1800) - 0.25) < 1e-9
    await agg.on_signal(make_signal("b", detector="funding_extreme", strength=1.0, created_at=T0, expires_at=T0 + timedelta(hours=4)))
    assert abs(agg.score("BTCUSDT", now=T0.timestamp()) - 1.0) < 1e-9     # 0.5 + 1.0×0.5

async def test_expired_signals_ignored(bus, st):
    agg = make_agg(bus, st)
    await agg.on_signal(make_signal("a", strength=1.0, created_at=T0 - timedelta(hours=2), expires_at=T0 - timedelta(hours=1)))
    assert agg.score("BTCUSDT") == 0.0

async def test_open_decision_when_threshold_crossed_and_notional_scaled(bus, st):
    got = []; bus.subscribe(Decision, lambda d: _append(got, d)); await bus.start()
    agg = make_agg(bus, st)
    await agg.on_signal(make_signal("a", detector="news_sentiment", direction=Direction.BEARISH, strength=0.7, created_at=T0, expires_at=T0 + timedelta(hours=4)))
    await bus.drain()
    d = got[0]
    assert d.intent == Intent.OPEN and d.side == Side.SELL and d.notional_usdt == Decimal("70") and d.signal_ids == ["a"] and d.stop_loss_pct == Decimal("0.01")
    assert (await st.count("decisions")) == 1

async def test_cooldown_blocks_second_decision(bus, st):
    t = [T0.timestamp()]; agg = make_agg(bus, st, clock=lambda: t[0])
    assert await agg.on_signal(make_signal("a", strength=0.9, created_at=T0, expires_at=T0 + timedelta(hours=4))) is not None
    assert await agg.on_signal(make_signal("b", strength=0.9, created_at=T0, expires_at=T0 + timedelta(hours=4))) is None
    t[0] += 900
    assert await agg.on_signal(make_signal("c", strength=0.9, created_at=T0, expires_at=T0 + timedelta(hours=4))) is not None

async def test_close_decision_on_flip_with_open_position(bus, st):
    pos = {"BTCUSDT": make_position(PositionSide.LONG, Decimal("0.002"), Decimal("80000"))}
    agg = make_agg(bus, st, positions=pos)
    d = await agg.on_signal(make_signal("b", detector="news_sentiment", direction=Direction.BEARISH, strength=0.5, created_at=T0, expires_at=T0 + timedelta(hours=1)))
    assert d.intent == Intent.CLOSE and d.side == Side.SELL and d.notional_usdt == Decimal("160")

async def test_no_open_when_position_exists_same_direction(bus, st):
    pos = {"BTCUSDT": make_position(PositionSide.LONG, Decimal("0.002"), Decimal("80000"))}
    assert await make_agg(bus, st, positions=pos).on_signal(make_signal("a", strength=0.9, created_at=T0, expires_at=T0 + timedelta(hours=1))) is None
```

- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现** — 内部 `_signals: dict[str, list[Signal]]`；`_last_decision_at: dict[str, float]`；决策 `id=new_id()`，`created_at` 由 `clock` 推导。
- [ ] **Step 4: 运行通过** — `uv run pytest -q && uv run ruff check .`
- [ ] **Step 5: 提交** — `git add -A && git commit -m "feat: signal aggregator producing open/close decisions"`

---

### Task 11: 风控引擎与杀开关

**Files:**
- Create: `src/ai_trader/risk/__init__.py`, `engine.py`, `kill_switch.py`, `src/ai_trader/execution/__init__.py`, `src/ai_trader/execution/broker.py`（仅 `Broker` Protocol）
- Test: `tests/unit/test_risk.py`

**Interfaces:**
- Produces: `RiskEngine(limits, store, state, allowed_symbols, *, clock=time.time)`、`RiskEngine.evaluate(d, account) -> RiskVerdict`、`KillSwitch(store, broker, bus)`（设计稿 5.8）；`Broker` Protocol = 设计稿 5.9 + `async def open_order_symbols(self) -> set[str]`。

- [ ] **Step 1: 写失败测试**

```python
def make_engine(st, state, **limits): return RiskEngine(RiskLimits(**limits), st, state, ["BTCUSDT", "ETHUSDT"], clock=lambda: T0.timestamp())
ACC = make_account(wallet=Decimal("10000"), positions=[])
# fixtures: st（打开的 Store）、state_fresh（有 BTCUSDT/ETHUSDT 标记价，clock 固定）、state_stale（空 MarketState）

async def test_approves_normal_open(st, state_fresh):
    v = await make_engine(st, state_fresh).evaluate(make_decision(notional=Decimal("100")), ACC)
    assert v.approved and v.reason is None and v.adjusted_notional is None

async def test_adjusts_notional_above_max(st, state_fresh):
    v = await make_engine(st, state_fresh).evaluate(make_decision(notional=Decimal("900")), ACC)
    assert v.approved and v.adjusted_notional == Decimal("200")

async def test_kill_switch_rejects_everything_including_close(st, state_fresh):
    await st.set_kv("kill_switch", "1")
    assert (await make_engine(st, state_fresh).evaluate(make_decision(intent=Intent.CLOSE), ACC)).reason == "kill_switch"

async def test_symbol_not_allowed(st, state_fresh):
    assert (await make_engine(st, state_fresh).evaluate(make_decision(symbol="DOGEUSDT"), ACC)).reason == "symbol_not_allowed"

async def test_stale_blocks_open_but_allows_close(st, state_stale):
    e = make_engine(st, state_stale)
    assert (await e.evaluate(make_decision(), ACC)).reason == "data_stale"
    assert (await e.evaluate(make_decision(intent=Intent.CLOSE), ACC)).approved

async def test_total_exposure(st, state_fresh):
    acc = make_account(wallet=Decimal("10000"), positions=[make_position(PositionSide.LONG, Decimal("0.005"), Decimal("80000"))])  # 400
    assert (await make_engine(st, state_fresh).evaluate(make_decision(notional=Decimal("150"), symbol="ETHUSDT"), acc)).reason == "max_total_exposure"

async def test_max_open_positions(st, state_fresh):
    acc = make_account(wallet=Decimal("10000"), positions=[make_position(PositionSide.LONG, Decimal("0.001"), Decimal("80000")),
                                                           make_position(PositionSide.SHORT, Decimal("0.01"), Decimal("3000"), symbol="ETHUSDT")])
    assert (await make_engine(st, state_fresh, max_total_exposure_usdt=Decimal("5000")).evaluate(make_decision(notional=Decimal("100")), acc)).reason == "max_open_positions"

async def test_daily_loss_limit_and_reset_on_new_utc_day(st, state_fresh):
    await make_engine(st, state_fresh).evaluate(make_decision(), ACC)          # 写入 day_start_equity:2026-10-29 = 10000
    await st.insert_fill(make_fill("c1", realized_pnl=Decimal("-600"), event_time=T0 + timedelta(hours=1)))
    e2 = RiskEngine(RiskLimits(), st, state_fresh, ["BTCUSDT"], clock=lambda: (T0 + timedelta(hours=2)).timestamp())
    assert (await e2.evaluate(make_decision(), ACC)).reason == "daily_loss_limit"
    e3 = RiskEngine(RiskLimits(), st, state_fresh, ["BTCUSDT"], clock=lambda: (T0 + timedelta(days=1, hours=1)).timestamp())
    assert (await e3.evaluate(make_decision(), ACC)).approved

async def test_consecutive_losses(st, state_fresh):
    for i in range(3): await st.insert_fill(make_fill(f"c{i}", realized_pnl=Decimal("-1"), event_time=T0 + timedelta(minutes=i)))
    assert (await make_engine(st, state_fresh).evaluate(make_decision(), ACC)).reason == "consecutive_losses"

async def test_verdicts_persisted(st, state_fresh):
    await make_engine(st, state_fresh).evaluate(make_decision(), ACC); assert await st.count("risk_verdicts") == 1

async def test_kill_switch_cancels_and_closes(st):
    class FakeBroker:
        def __init__(self): self.cancel_all_calls, self.close_calls = set(), []
        async def positions(self): return {"BTCUSDT": make_position(PositionSide.LONG, Decimal("0.002"), Decimal("80000"))}
        async def open_order_symbols(self): return {"ETHUSDT"}
        async def cancel_all(self, s): self.cancel_all_calls.add(s)
        async def close_position(self, s): self.close_calls.append(s); return None
    broker = FakeBroker(); bus = EventBus(); events = []; bus.subscribe(KillSwitchTriggered, lambda e: _append(events, e))
    ks = KillSwitch(st, broker, bus); await bus.start(); await ks.trigger("test"); await bus.drain(); await bus.stop()
    assert await ks.is_active() and broker.cancel_all_calls == {"BTCUSDT", "ETHUSDT"} and broker.close_calls == ["BTCUSDT"]
    assert events[-1].reason == "test"
```

- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现** — `evaluate` 中 UTC 日期用 `datetime.fromtimestamp(clock(), timezone.utc).date().isoformat()`；日亏损阈值 `-(max_daily_loss_pct/100) * day_start_equity`，与 `realized_pnl_since(当日 00:00 UTC)` 比较。`KillSwitch.trigger` 对 `positions().keys() | open_order_symbols()` 的每个 symbol 先 `cancel_all` 再（有仓时）`close_position`，单个 symbol 失败记日志继续。
- [ ] **Step 4: 运行通过** — `uv run pytest -q && uv run ruff check .`
- [ ] **Step 5: 提交** — `git add -A && git commit -m "feat: risk engine with hard limits and kill switch"`

---

### Task 12: 执行层：模拟经纪商、币安经纪商、执行服务

**Files:**
- Create: `src/ai_trader/execution/paper.py`, `binance.py`, `service.py`
- Test: `tests/unit/test_paper_broker.py`, `tests/unit/test_binance_broker.py`, `tests/unit/test_execution.py`

**Interfaces:**
- Consumes: Task 3/4 REST 与 WS、Task 5 Store、Task 11 `RiskEngine` 与 `Broker` Protocol。
- Produces: `PaperBroker`（含 `submitted: list[OrderRequest]`）、`BinanceFuturesBroker`（含 `async reconcile()`）、`ExecutionService`（含 `async handle_decision(d)`、`async enforce_max_hold()`、`async start()`）。测试用 `fake_ws_factory(url, handler)` 放入 `tests/conftest.py`：返回带 `run()/stop()` 的对象并把 `handler` 存到 `fake_ws_factory.handlers[url]`。

- [ ] **Step 1: 写失败测试（PaperBroker）**

```python
async def test_market_fill_with_slippage_and_fee(bus, state, exchange_info):
    state.update_mark(make_mark_price(mark=Decimal("80000"))); fills = []; bus.subscribe(Fill, lambda e: _append(fills, e))
    pb = PaperBroker(state, bus, exchange_info, slippage_bps=2); await bus.start(); await pb.start()
    res = await pb.submit(OrderRequest(symbol="BTCUSDT", side=Side.BUY, type=OrderType.MARKET, quantity=Decimal("0.002"), client_order_id="ait-1"))
    assert res.status == OrderStatus.FILLED and res.avg_price == Decimal("80016.00")
    await bus.drain(); assert fills[0].commission == Decimal("0.002") * Decimal("80016.00") * Decimal("0.0004")
    pos = await pb.positions(); assert pos["BTCUSDT"].side == PositionSide.LONG and pos["BTCUSDT"].quantity == Decimal("0.002")

async def test_stop_market_close_position_triggers_on_mark(bus, state, exchange_info):
    ...  # 开多 0.002@80016 后挂 STOP_MARKET close_position stop 79000.0；publish MarkPrice 79500 → 持仓不变；78990 → positions() 空，最后一个 Fill.realized_pnl < 0

async def test_close_position_flat_returns_none(bus, state, exchange_info):
    pb = PaperBroker(state, bus, exchange_info); assert await pb.close_position("ETHUSDT") is None
```

- [ ] **Step 2: 写失败测试（BinanceFuturesBroker）**

```python
@respx.mock
async def test_submit_timeout_then_found_does_not_resend(bus, exchange_info):
    post = respx.post(f"{BASE}/fapi/v1/order").mock(side_effect=httpx.ReadTimeout("t"))
    get = respx.get(f"{BASE}/fapi/v1/order").mock(return_value=httpx.Response(200, json=fx("order_response.json") | {"clientOrderId": "ait-abc", "status": "FILLED"}))
    br = BinanceFuturesBroker(BinanceFuturesRest(BASE, "k", "s"), exchange_info, bus, "wss://x", ws_factory=fake_ws_factory)
    res = await br.submit(OrderRequest(symbol="BTCUSDT", side=Side.BUY, type=OrderType.MARKET, quantity=Decimal("0.002"), client_order_id="ait-abc"))
    assert res.status == OrderStatus.FILLED and post.call_count == 1 and get.call_count == 1

@respx.mock
async def test_submit_timeout_and_not_found_raises(bus, exchange_info):
    respx.post(f"{BASE}/fapi/v1/order").mock(side_effect=httpx.ReadTimeout("t"))
    respx.get(f"{BASE}/fapi/v1/order").mock(return_value=httpx.Response(400, json={"code": -2013, "msg": "Order does not exist."}))
    with pytest.raises(BinanceConnectionError): await br.submit(...)

async def test_submit_validates_filters_first(bus, exchange_info):
    with pytest.raises(FilterViolation): await br.submit(OrderRequest(symbol="BTCUSDT", side=Side.BUY, type=OrderType.MARKET, quantity=Decimal("0.0015"), client_order_id="ait-z"))

@respx.mock
async def test_user_stream_fill_published_and_positions_updated(bus, exchange_info):
    respx.post(f"{BASE}/fapi/v1/listenKey").mock(return_value=httpx.Response(200, json={"listenKey": "LK"}))
    respx.get(f"{BASE}/fapi/v2/positionRisk").mock(return_value=httpx.Response(200, json=[]))
    fills = []; bus.subscribe(Fill, lambda e: _append(fills, e)); await bus.start()
    br = BinanceFuturesBroker(BinanceFuturesRest(BASE, "k", "s"), exchange_info, bus, "wss://x", ws_factory=fake_ws_factory); await br.start()
    h = fake_ws_factory.handlers["wss://x/ws/LK"]
    await h(fx("ws_order_trade_update_fill.json")); await h(fx("ws_account_update.json")); await bus.drain()
    assert fills[0].client_order_id == "ait-abc" and (await br.positions())["BTCUSDT"].quantity == Decimal("0.002")
    await br.stop()

@respx.mock
async def test_reconcile_mismatch_triggers_kill(bus, exchange_info):
    respx.get(f"{BASE}/fapi/v2/positionRisk").mock(return_value=httpx.Response(200, json=fx("position_risk_v2.json")))  # 远端 BTC 空 0.002
    killed = []; events = []; bus.subscribe(ReconcileMismatch, lambda e: _append(events, e)); await bus.start()
    async def kill(reason): killed.append(reason)
    br = BinanceFuturesBroker(BinanceFuturesRest(BASE, "k", "s"), exchange_info, bus, "wss://x", ws_factory=fake_ws_factory, kill=kill)
    await br.reconcile(); await bus.drain()
    assert events[-1].symbol == "BTCUSDT" and events[-1].remote_qty == Decimal("0.002") and killed and "BTCUSDT" in killed[0]
```

- [ ] **Step 3: 写失败测试（ExecutionService）**

```python
class AlwaysApprove:
    def __init__(self, adjusted=None): self.adjusted = adjusted
    async def evaluate(self, d, acc): return RiskVerdict(approved=True, adjusted_notional=self.adjusted)
class AlwaysReject:
    async def evaluate(self, d, acc): return RiskVerdict(approved=False, reason="test")

async def test_approved_open_places_entry_then_sl_tp(bus, st, state, exchange_info):
    state.update_mark(make_mark_price(mark=Decimal("80000"))); paper = PaperBroker(state, bus, exchange_info); await bus.start(); await paper.start()
    svc = ExecutionService(bus, paper, AlwaysApprove(), st, Settings(_env_file=None), clock=lambda: T0.timestamp())
    await svc.handle_decision(make_decision(side=Side.BUY, notional=Decimal("160")))
    o = paper.submitted
    assert [x.type for x in o] == [OrderType.MARKET, OrderType.STOP_MARKET, OrderType.TAKE_PROFIT_MARKET]
    assert o[0].quantity == Decimal("0.002")
    assert o[1].close_position and o[1].side == Side.SELL and o[1].stop_price == Decimal("79215.80")   # 80016 × 0.99 向下取 tick
    assert o[2].stop_price == Decimal("81616.30")                                                      # 80016 × 1.02
    assert [(await st.get_order(x.client_order_id)).role for x in o] == [OrderRole.ENTRY, OrderRole.STOP_LOSS, OrderRole.TAKE_PROFIT]

async def test_rejected_decision_places_nothing(...): ...   # AlwaysReject → paper.submitted == []
async def test_adjusted_notional_used(...): ...             # AlwaysApprove(Decimal("200")) 且决策 900 → qty 0.002
async def test_open_skipped_when_filter_violation(...):      # 决策名义 50 → paper.submitted == []，caplog 含 "FilterViolation"
async def test_close_decision_cancels_protective_and_closes(...): ...  # 先开仓；handle_decision(CLOSE) → paper 收到 cancel_all 1 次、close_position 1 次；store 有 role CLOSE 订单
async def test_protective_fill_cancels_sibling(...): ...    # 开仓后 publish Fill(client_order_id=SL 的 id) → paper.cancel 被调用且参数为 TP 的 id
async def test_max_hold_emits_close(...): ...               # 开仓后 clock = T0 + 14401 → enforce_max_hold() → bus 收到 Decision(intent=CLOSE)
```

- [ ] **Step 4: 运行确认失败** — 三个测试文件均 ImportError。
- [ ] **Step 5: 实现 `paper.py`、`binance.py`、`service.py`** — 按设计稿 5.9。`ExecutionService` 持 `_entry_time: dict[str, float]`。SL 价格：BUY 入场 → `avg × (1 − sl)`，SELL 入场 → `avg × (1 + sl)`；TP 相反；均 `filters.round_price`。`handle_decision` 捕获 `FilterViolation` 记 `log.warning("FilterViolation ...")` 并返回。`PaperBroker.cancel/cancel_all` 记录调用（`cancel_calls: list[str]`、`cancel_all_calls: list[str]`）。
- [ ] **Step 6: 运行通过** — `uv run pytest -q && uv run ruff check .`
- [ ] **Step 7: 提交** — `git add -A && git commit -m "feat: paper and Binance futures brokers with execution service"`

---

### Task 13: 应用装配、前瞻收益追踪与完整 CLI

**Files:**
- Create: `src/ai_trader/analysis/forward_returns.py`, `src/ai_trader/app.py`
- Modify: `src/ai_trader/cli.py`（`run`、`kill`、`status`、`signals`）
- Test: `tests/unit/test_forward_returns.py`, `tests/unit/test_app.py`, `tests/unit/test_cli.py`

**Interfaces:**
- Produces: `ForwardReturnTracker(store, state, *, horizons_s=(600, 3600, 14400), interval_s=60, clock=time.time)`（`async tick()`、`async run()`、`async stop()`）；`Components` dataclass（字段 `settings, bus, store, state, rest, broker, feed, watchdog, sampler, detectors, runner, poller, aggregator, risk, kill_switch, execution, tracker`）；`async create_components(settings, *, rest=None, ws_factory=None, http=None, store=None) -> Components`（async：内部 `await rest.exchange_info()`；`http` 为 RSS/X/DeepSeek 共用的 `httpx.AsyncClient`）；`App(components)` 的 `async run()`、`async stop()`；`App.run()` 用监督器运行每个长期组件：组件协程抛出 `Exception` 时记录 `log.exception`、按 1/2/5/10/30 s 退避后重启，直到 `stop()`；CLI 子命令 `probe/run/kill/status/signals/classify/version`。

- [ ] **Step 1: 写失败测试**

```python
async def test_forward_return_computed_from_samples(st):
    await st.insert_signal(make_signal("s1", direction=Direction.BEARISH, ref_price=Decimal("80000"), created_at=T0))
    await st.insert_mark_sample("BTCUSDT", T0 + timedelta(seconds=600), Decimal("79200"))
    tr = ForwardReturnTracker(st, MarketState(), horizons_s=(600,), clock=lambda: (T0 + timedelta(seconds=700)).timestamp())
    await tr.tick()
    rows = await st.effectiveness(); assert rows[0].n == 1 and abs(rows[0].mean_ret - 0.01) < 1e-9   # (79200-80000)/80000 × (-1)

async def test_forward_return_skips_when_no_sample(st):
    await st.insert_signal(make_signal("s1", created_at=T0))
    tr = ForwardReturnTracker(st, MarketState(), horizons_s=(600,), clock=lambda: (T0 + timedelta(seconds=700)).timestamp())
    await tr.tick(); assert await st.effectiveness() == []

async def test_create_components_paper_mode_wires_without_network(tmp_path, exchange_info):
    s = Settings(_env_file=None, mode="paper", db_path=tmp_path / "a.db", llm=LLMConfig(enabled=False))
    c = await create_components(s, rest=FakeRest(exchange_info), ws_factory=fake_ws_factory,
                          http=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404))))
    assert isinstance(c.broker, PaperBroker) and len(c.detectors) == 3 and c.risk is not None

async def test_app_start_stop_cleanly(tmp_path, exchange_info):
    c = await create_components(...同上...); app = App(c)
    task = asyncio.create_task(app.run()); await asyncio.sleep(0.2); await app.stop(); await asyncio.wait_for(task, 5)

async def test_app_restarts_crashed_component(tmp_path, exchange_info):
    ...  # 用一个 run() 先抛 RuntimeError 再正常阻塞的假组件替换 c.poller；App.run() 后 0.3 s 内该组件被调用 ≥ 2 次且 app 仍在运行；caplog 含 "restarting"

def test_cli_run_live_mainnet_requires_confirm(monkeypatch):
    monkeypatch.setenv("BINANCE_TESTNET", "false")
    r = CliRunner().invoke(app, ["run", "--mode", "live"])
    assert r.exit_code == 2 and "--confirm-mainnet" in r.output

def test_cli_signals_prints_table(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "x.db"))
    asyncio.run(_seed(tmp_path / "x.db"))     # 写入 1 条 funding_extreme 信号 + forward_return(600)
    r = CliRunner().invoke(app, ["signals"]); assert r.exit_code == 0 and "funding_extreme" in r.output and "600" in r.output
```
`FakeRest(exchange_info)`：`async exchange_info()` 返回传入对象，`async sync_time()` 返回 0，`async premium_index(sym)` 返回 `make_mark_price(symbol=sym)`；放入 `tests/conftest.py`。

- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现** — `create_components`：`mode=="live"` 且缺 key → `raise SystemExit("live 模式需要 BINANCE_API_KEY/BINANCE_API_SECRET")`；`settings.llm.enabled and settings.llm.provider == "deepseek" and settings.deepseek_api_key` 时用 `DeepSeekClassifier(http, key, symbols, model=..., base_url=..., fallback=KeywordClassifier, budget=DailyBudget(llm.daily_call_budget), ...)`，否则 `KeywordClassifier`；X 源仅在 `news.x_bearer_token` 存在时加入；`create_components` 为 async，内部 `await rest.exchange_info()`（测试通过 `FakeRest`）。`App.run()` 用 `asyncio.TaskGroup` 承载一组 `_supervise(name, factory)` 任务（见 Interfaces 的监督器要求）；`stop()` 设置 `asyncio.Event` 后各组件 `stop()`。CLI `run`：`asyncio.run(...)`，`loop.add_signal_handler` 在 Windows 抛 `NotImplementedError` 时改为捕获 `KeyboardInterrupt`。`status`/`kill`：直接构造 `Store` 与（live 时）REST；`kill` 在 paper 模式只写 kv。
- [ ] **Step 4: 运行通过** — `uv run pytest -q && uv run ruff check .`
- [ ] **Step 5: 提交** — `git add -A && git commit -m "feat: app wiring, forward-return tracker and full CLI"`

---

### Task 14: 文档、环境样例、集成测试与测试网演练

**Files:**
- Create: `README.md`, `.env.example`, `tests/integration/__init__.py`, `tests/integration/test_testnet.py`

- [ ] **Step 1: 写集成测试（默认 skip）**

```python
pytestmark = pytest.mark.integration
KEY, SEC = os.getenv("BINANCE_API_KEY"), os.getenv("BINANCE_API_SECRET")
skip = pytest.mark.skipif(not (KEY and SEC), reason="需要测试网 BINANCE_API_KEY/SECRET")

@skip
async def test_account_and_positions():
    rest = BinanceFuturesRest(TESTNET_REST, KEY, SEC); await rest.sync_time()
    assert (await rest.account()).total_wallet_balance >= 0

@skip
async def test_place_far_limit_then_cancel():
    rest = BinanceFuturesRest(TESTNET_REST, KEY, SEC); await rest.sync_time()
    f = (await rest.exchange_info()).filters_for("BTCUSDT"); mark = (await rest.premium_index("BTCUSDT")).mark_price
    price = f.round_price(mark * Decimal("0.5")); qty = f.qty_for_notional(Decimal("120"), price); cid = new_client_order_id()
    res = await rest.place_order(OrderRequest(symbol="BTCUSDT", side=Side.BUY, type=OrderType.LIMIT, quantity=qty, price=price, client_order_id=cid, time_in_force="GTC"))
    assert res.status == OrderStatus.NEW
    assert (await rest.cancel_order("BTCUSDT", client_order_id=cid)).status == OrderStatus.CANCELED

@pytest.mark.network
@pytest.mark.skipif(os.getenv("AIT_NETWORK_TESTS") != "1", reason="AIT_NETWORK_TESTS=1 才跑")
async def test_public_ping_and_mark():
    rest = BinanceFuturesRest(TESTNET_REST); await rest.ping(); assert (await rest.premium_index("BTCUSDT")).mark_price > 0
```

- [ ] **Step 2: 写 `.env.example` 与 `README.md`**

`.env.example` 列出全部顶层与嵌套变量及默认值（key 留空）。`README.md`（中文）：项目定位与预期（引用设计稿第 8 节的提醒）、本地网络限制与测试网说明（含 Demo Trading 域名不可达）、快速开始（`uv sync --group dev` → 填 `.env` → `uv run ai-trader probe` → `uv run ai-trader run --mode paper` → `uv run ai-trader run --mode live`）、CLI 一览、架构图、配置表、风控与杀开关说明、X 与 Claude 成本控制、如何加探测器/新闻源、测试命令、主网启用步骤与警告。

- [ ] **Step 3: 全量验证** — `uv run pytest -q`（集成测试 skipped）；`uv run ruff check .`；`uv run ai-trader probe`；`AIT_NETWORK_TESTS=1 uv run pytest -q -m network`。

- [ ] **Step 4: 测试网 paper 演练 2 分钟**

后台运行 `uv run ai-trader run --mode paper`，120 s 后停止；然后
`uv run python -c "import sqlite3;c=sqlite3.connect('data/ai_trader.db');print(c.execute('select count(*) from mark_samples').fetchone(), c.execute('select count(*) from signals').fetchone())"`
→ `mark_samples` 计数 ≥ 10；日志无 Traceback；`uv run ai-trader status` 正常输出。

- [ ] **Step 5: 提交** — `git add -A && git commit -m "docs: README, env example and testnet integration tests"`

---

### Task 15: 自动调参器（AutoTuner）

**Files:**
- Create: `src/ai_trader/strategy/autotune.py`
- Modify: `src/ai_trader/models.py`（新增 `TuningChange`）、`src/ai_trader/storage/db.py`（新增 `tuning_log` 表与 `insert_tuning_change(change)`、`tuning_log(limit) -> list[TuningChange]`、`count_signals_since(ts) -> int`、`count_decisions_since(ts) -> int`）、`src/ai_trader/app.py`（装配并启动 AutoTuner）、`src/ai_trader/cli.py`（新增 `tuning` 子命令；`status` 打印当前生效的 `entry_threshold`、`base_notional_usdt`、`cooldown_s`、`detector_weights`、三个探测器阈值）
- Test: `tests/unit/test_autotune.py`

**Interfaces:**
- Consumes: `Store.effectiveness()`、`Store.realized_pnl_since`、`Store.get_kv("day_start_equity:<UTC date>")`、`StrategyConfig`、`DetectorConfig`（两者为可变 pydantic 模型；聚合器/探测器/执行服务在每次使用时读取字段，而非构造时缓存）。
- Produces: `TuningChange(ts: datetime, rule: str, field: str, old: str, new: str, reason: str)`（frozen 模型）；`AutoTuner(store, strategy_cfg: StrategyConfig, detector_cfg: DetectorConfig, *, interval_s: int = 1800, activity_window_s: int = 7200, clock=time.time)`，属性 `strategy_cfg`/`detector_cfg`，方法 `async tick() -> list[TuningChange]`、`async run()`、`async stop()`。

规则（每次 `tick` 依次评估，每条规则每次最多一步，所有改动落库并打日志；**绝不修改 `RiskLimits`**）：

1. `activity_floor`：最近 `activity_window_s` 内信号数 < 3 且决策数 == 0 → `detector_cfg.liquidation_notional_threshold_usdt *= 0.7`（下限 5000）、`detector_cfg.news_min_confidence -= 0.05`（下限 0.3）、`detector_cfg.funding_annualized_threshold *= 0.8`（下限 0.05）、`strategy_cfg.entry_threshold -= 0.05`（下限 0.3）。
2. `detector_quality`：对 `effectiveness()` 中 `horizon_s == 3600` 且 `n >= 20` 的探测器：`hit_rate < 0.40 and mean_ret < 0` → `detector_weights[d] = max(0.0, w - 0.25)`；`hit_rate >= 0.55 and mean_ret > 0` → `detector_weights[d] = min(1.5, w + 0.1)`。
3. `loss_brake`：当日已实现盈亏 ≤ −2% × 当日起始权益（kv 缺失则跳过）→ `strategy_cfg.base_notional_usdt *= 0.5`（下限 20）且 `entry_threshold += 0.1`（上限 0.9）；当日 ≥ +2% 且 `base_notional_usdt < 100` → `base_notional_usdt = min(100, ×1.25)`。
4. `overtrading_brake`：最近 `activity_window_s` 内决策数 ≥ 10 → `strategy_cfg.cooldown_s = min(3600, int(cooldown_s × 1.5))` 且 `entry_threshold += 0.05`（上限 0.9）。

- [ ] **Step 1: 写失败测试**

```python
def mk(st, clock=None, **kw): return AutoTuner(st, StrategyConfig(), DetectorConfig(), clock=clock or (lambda: T0.timestamp()), **kw)

async def test_activity_floor_relaxes_thresholds_one_step(st):
    t = mk(st); changes = await t.tick()
    assert t.detector_cfg.liquidation_notional_threshold_usdt == Decimal("35000") and abs(t.detector_cfg.news_min_confidence - 0.55) < 1e-9
    assert abs(t.strategy_cfg.entry_threshold - 0.55) < 1e-9 and {c.rule for c in changes} == {"activity_floor"}
    assert len(await st.tuning_log(10)) == len(changes)

async def test_activity_floor_respects_floors(st):
    t = mk(st)
    for _ in range(40): await t.tick()
    assert t.detector_cfg.liquidation_notional_threshold_usdt >= Decimal("5000") and t.detector_cfg.news_min_confidence >= 0.3 - 1e-9 and t.strategy_cfg.entry_threshold >= 0.3 - 1e-9

async def test_activity_floor_not_triggered_when_active(st):
    for i in range(3): await st.insert_signal(make_signal(f"s{i}", created_at=T0 - timedelta(minutes=10)))
    await st.insert_decision(make_decision_model(created_at=T0 - timedelta(minutes=5)))
    assert [c for c in await mk(st).tick() if c.rule == "activity_floor"] == []

async def test_detector_quality_disables_bad_and_boosts_good(st):
    await seed_effectiveness(st, "funding_extreme", horizon_s=3600, n=25, hit_rate=0.3, mean_ret=-0.002)
    await seed_effectiveness(st, "news_sentiment", horizon_s=3600, n=25, hit_rate=0.6, mean_ret=0.003)
    t = mk(st); await t.tick()
    assert abs(t.strategy_cfg.detector_weights["funding_extreme"] - 0.25) < 1e-9 and abs(t.strategy_cfg.detector_weights["news_sentiment"] - 1.1) < 1e-9

async def test_detector_quality_ignores_small_samples(st):
    await seed_effectiveness(st, "funding_extreme", horizon_s=3600, n=5, hit_rate=0.0, mean_ret=-0.01)
    t = mk(st); await t.tick(); assert t.strategy_cfg.detector_weights["funding_extreme"] == 0.5

async def test_loss_brake_halves_notional(st):
    await st.set_kv("day_start_equity:2026-10-29", "10000")
    await st.insert_fill(make_fill("c1", realized_pnl=Decimal("-250"), event_time=T0 - timedelta(hours=1)))
    t = mk(st); await t.tick()
    assert t.strategy_cfg.base_notional_usdt == Decimal("50") and abs(t.strategy_cfg.entry_threshold - 0.65) < 1e-9   # 0.6 − 0.05 (activity_floor) + 0.1

async def test_overtrading_brake(st):
    for i in range(10): await st.insert_decision(make_decision_model(created_at=T0 - timedelta(minutes=i)))
    t = mk(st); await t.tick(); assert t.strategy_cfg.cooldown_s == 1350

async def test_never_touches_risk_limits(st): ...  # AutoTuner 没有 RiskLimits 引用；断言 StrategyConfig/DetectorConfig 以外无字段被改（通过 tuning_log 的 field 前缀检查）
```
`seed_effectiveness(st, detector, *, horizon_s, n, hit_rate, mean_ret)` 与 `make_decision_model(created_at=...)` 放入 `tests/conftest.py`：前者插入 `n` 条信号及对应前瞻收益（`round(n*hit_rate)` 条正收益、其余负收益，均值等于 `mean_ret`），使 `effectiveness()` 产生给定的 `n`/`hit_rate`/`mean_ret`。

- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现** — `autotune.py`；`Store` 新增表 `tuning_log(ts, rule, field, old, new, reason)` 与计数方法；`app.py` 在 `create_components` 中构造 `AutoTuner(store, settings.strategy, settings.detectors)` 并在 `App.run()` 中受监督地运行；`cli.py` 新增 `tuning`（打印最近 50 条调参记录）并在 `status` 中打印当前生效参数。确认 `SignalAggregator`、三个探测器、`ExecutionService` 均在使用时读取配置字段（若发现构造时缓存，改为属性访问并补一个回归测试）。
- [ ] **Step 4: 运行通过** — `uv run pytest -q && uv run ruff check .`
- [ ] **Step 5: 提交** — `git add -A && git commit -m "feat: auto-tuner adjusting thresholds and weights from live effectiveness"`

---

### Task 16: 夜间模拟盘启动与看门狗（控制器执行，不派发实施者）

- [ ] **Step 1**: `uv run ai-trader probe` 通过；`uv run pytest -q` 全绿。
- [ ] **Step 2**: 以独立进程启动模拟盘（PowerShell `Start-Process uv -ArgumentList run,ai-trader,run,--mode,paper -WindowStyle Hidden`，`stdout/stderr` 重定向到 `data/paper-run.log` / `data/paper-run.err.log`），启动前通过环境变量注入夜间配置：`NEWS__RSS_FEEDS`（账本中 14 个可达源的 JSON 数组）、`DETECTORS__NEWS_MIN_CONFIDENCE=0.3`、`DETECTORS__LIQUIDATION_NOTIONAL_THRESHOLD_USDT=10000`。
- [ ] **Step 3**: 3 分钟后验证：`mark_samples` 增长、`news` 表有记录、日志无 Traceback、`ai-trader status` 正常；记录 PID 到 `data/paper-run.pid`。
- [ ] **Step 4**: 会话内 cron 看门狗（每 45 分钟）：检查 PID 存活与 `mark_samples` 最近 5 分钟是否有新样本；若进程死亡或数据停滞 → 从 `data/paper-run.err.log` 取最后 40 行记入账本并重启；每次把 `status`/`signals`/`tuning` 摘要追加到 `data/overnight-report.md`。
- [ ] **Step 5**: 最终消息告诉用户：如何看结果（`ai-trader status` / `signals` / `tuning`、`data/overnight-report.md`、日志路径）、如何停止（`taskkill /PID <pid> /T /F`）、如何加 X token 与切换 live。

---

## 自检记录

- 覆盖：设计稿 5.1→T1，5.2/5.3→T2，5.4→T3/T4，5.5→T6/T8，5.6→T7/T9，5.7→T10，5.8→T11，5.9→T11（Protocol）/T12，5.10→T5/T13，5.11→T13，第 6 节→各任务 + T14。
- 类型一致：`Broker` Protocol 在 T11 声明（含 `open_order_symbols`）、T12 实现；`DailyBudget` 在 T8 定义（含 `refund`）、T9 复用；`EffectivenessRow` 在 T5 定义、T13 CLI 使用；`Store.count(table)` 在 T6 加入、T9/T10/T11 使用；`fake_ws_factory`、`FakeRest` 与各 `make_*` 构造函数集中在 `tests/conftest.py`。
- Review Focus 五项分别对应 T3/T12、T12、T11、T11、T9 的具名测试。
- 变更 2026-10-29 深夜：Task 9 改为 DeepSeek（用户提供 DEEPSEEK_API_KEY）；Task 13 的 create_components 改为 async 并加入组件监督器；新增 Task 15 AutoTuner（用户要求实测数据不好时自动调整策略）与 Task 16 夜间启动流程。
