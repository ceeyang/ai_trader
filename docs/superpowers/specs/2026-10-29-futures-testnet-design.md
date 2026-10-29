# ai_trader v2：币安 USDT 本位合约事件驱动交易系统（测试网优先）设计稿

日期：2026-10-29 | 分支：`futures-rewrite`（孤儿分支，旧代码保留在 `main`） | 状态：用户选择跳过需求问答，以下所有选型均为 Claude 的决定，标注为 **[我的决定]**，用户可随时推翻。

---

## 1. 意图与背景

用户的目标：把项目改造成 **读取实时行情、抓取 X 热点和官方信息、判断利好利空、自动做合约** 的系统，从零开始，优先接入币安合约 **测试网**。

前置调研（`main` 分支 `docs/research/crypto-futures-signals-2026-10-29.md`）的核心结论原样继承：

- 公开数据下的短周期方向预测准确率上限约 50–52%，扣费后接近零。个人能稳定抓到的机会来自结构性错位和事件，不是方向判断。
- 因此本系统的设计重心是：**每个信号都记录前瞻收益，先跑测试网/模拟盘至少一个月，用数据决定哪些探测器值得用真钱**；风控独立于策略，杀开关独立于一切。

本地环境事实（2026-10-29 实测）：

| 端点 | 状态 |
|---|---|
| `https://testnet.binancefuture.com` REST | 通，0.5 s，743 个合约 |
| `wss://stream.binancefuture.com` WS | 通，markPrice / aggTrade / forceOrder 均有推送 |
| `https://fapi.binance.com`、`wss://fstream.binance.com` | 超时（DNS 劫持） |
| `https://demo-fapi.binance.com`（Demo Trading） | 超时 |
| `https://www.binance.com/bapi/...`（公告） | 超时 |
| X API | 2026-09 起仅按量付费：读 1 条 0.005 美元，无免费层 |

结论：**所有默认值指向测试网**；主网需要同时满足配置 `BINANCE_TESTNET=false` 和命令行 `--confirm-mainnet`，并且必须在海外服务器或代理环境运行。

## 2. 目标 / 非目标 / 反目标

**目标（Phase 1，本计划）**

1. 单进程 asyncio 守护进程，打通闭环：行情 → 探测器 → 信号 → 聚合 → 风控 → 下单 → 成交回报 → 对账。
2. 币安 USDT 本位合约 REST（签名）+ WebSocket（行情流 + 用户数据流）客户端，测试网可用，主网仅换 URL。
3. 新闻/社交接入：RSS（免费）+ X API v2 近期搜索（按量付费，带每日读取预算）。
4. 利多/利空判断：Claude 结构化输出分类器，附关键词规则兜底，带每日调用预算。
5. 两个纯行情探测器（资金费率极端、清算爆发）作为不依赖外部付费服务的基线信号。
6. 独立风控引擎 + 杀开关；模拟经纪商（paper）与币安经纪商（live）同一接口。
7. SQLite 落库：新闻、情绪、信号、前瞻收益、决策、风控裁决、订单、成交；CLI 查看信号有效性表。
8. 单元测试不碰网络；集成测试仅在提供测试网 key 时运行。
9. 自动调参器：根据实测信号有效性与活跃度自动调整探测器阈值、权重、名义与冷却（5.12），全部留痕。

**非目标（Phase 2 再做）**

- Web 面板（旧版的 FastAPI + React 不保留，后续按需重建，直接读 SQLite）。
- 多交易所、币本位合约、期权、回测引擎、持仓量/基差/跨所价差探测器、宏观日历、币安公告（本地不可达，需海外节点）。

**反目标（出现即为失败）**

- 任何订单绕过风控引擎直达交易所。
- 日志或数据库出现 API key / secret / bearer token 明文。
- 交易所错误、WS 断线、分类器异常被静默吞掉；它们必须变成日志 + 事件，并在该停的时候停。
- 默认配置能在主网下单。

## 3. 约束

- Python ≥ 3.12，`uv` 管理，`src/` 布局，包名仍为 `ai_trader`，全异步。
- 价格与数量全程 `Decimal`；时间全程 tz-aware UTC。
- 依赖 **[我的决定]**：`httpx`（REST）、`websockets`（WS）、`pydantic` v2 + `pydantic-settings`（模型与配置，`.env`）、`anthropic`（分类器）、`aiosqlite`（存储）、`typer`（CLI）、`feedparser`（RSS）。开发：`pytest`、`pytest-asyncio`、`respx`、`ruff`、`mypy`。
- LLM 分类器 **[用户决定 2026-10-29 深夜]**：DeepSeek（用户提供 `DEEPSEEK_API_KEY`）。OpenAI 兼容 `POST https://api.deepseek.com/chat/completions`，`model="deepseek-chat"`，`response_format={"type":"json_object"}`，`temperature=0`，`max_tokens=512`，用项目已有 `httpx` 调用，不引入额外 SDK；任何失败退化为关键词分类器。
- X 搜索每次 `max_results` 默认 10，轮询 120 s，每日读取预算默认 2000 条（约 10 美元/天上限）。
- 单元测试禁止真实网络；WS 测试用本机回环假服务器。

## 4. 架构

```
                 ┌──────────────────────── EventBus（按类型订阅，每订阅者独立队列）────────────────────────┐
                 │                                                                                           │
 Binance WS ──► MarketFeed ──► MarkPrice / Kline / Liquidation ──► FundingExtremeDetector ─┐                 │
   (testnet)       │                                             LiquidationBurstDetector ─┤                 │
                   └─► MarketState（最新标记价、新鲜度）         NewsSentimentDetector ────┼─► Signal ──► SignalAggregator ──► Decision
 RSS / X API ──► NewsPoller ──► NewsItem ──► ClaudeClassifier(→KeywordClassifier 兜底) ───┘       │                         │
                                                                                                 Store(SQLite)        RiskEngine ──► RiskVerdict
 StalenessWatchdog ──► DataStale / DataFresh                                                                                │
 KillSwitch ──► KillSwitchTriggered                                                                             ExecutionService
 ForwardReturnTracker（信号前瞻收益 10m/1h/4h）                                                                        │
                                                                                                  Broker 接口：PaperBroker | BinanceFuturesBroker
                                                                                                                 │  用户数据流 Fill / 持仓更新 ──► bus
                                                                                                                 └  每 60 s REST 对账，不一致 → 杀开关
```

一切组件只通过 `EventBus` 和 `Store` 耦合。`MarketState` 是唯一的进程内共享状态（最新标记价）。

## 5. 模块与接口清单（实施计划逐字引用）

### 5.1 `ai_trader/settings.py`

`Settings(BaseSettings)`：`env_file=".env"`，`env_nested_delimiter="__"`，`extra="ignore"`。字段与默认值：

| 字段 | 默认 | 说明 |
|---|---|---|
| `binance_api_key: SecretStr \| None` | None | |
| `binance_api_secret: SecretStr \| None` | None | |
| `binance_testnet: bool` | True | |
| `binance_rest_url: str \| None` / `binance_ws_url: str \| None` | None | 为空时按 testnet 推导：`https://testnet.binancefuture.com` / `wss://stream.binancefuture.com`；主网 `https://fapi.binance.com` / `wss://fstream.binance.com`。属性 `effective_rest_url`、`effective_ws_url` |
| `symbols: list[str]` | `["BTCUSDT","ETHUSDT"]` | |
| `leverage: int` | 2 | |
| `margin_type: Literal["ISOLATED","CROSSED"]` | "ISOLATED" | |
| `mode: Literal["paper","live"]` | "paper" | paper = 真实测试网行情 + 模拟成交 |
| `db_path: Path` | `data/ai_trader.db` | |
| `log_level: str` / `log_json: bool` | "INFO" / False | |
| `risk: RiskLimits` | 见下 | 环境变量 `RISK__MAX_LEVERAGE` 等 |
| `strategy: StrategyConfig` | 见下 | |
| `detectors: DetectorConfig` | 见下 | |
| `news: NewsConfig` | 见下 | |
| `deepseek_api_key: SecretStr \| None` | None | 来自 `.env` 的 `DEEPSEEK_API_KEY` |
| `llm: LLMConfig` | 见下 | |

`RiskLimits`：`max_leverage=3`，`max_order_notional_usdt=Decimal("200")`，`max_total_exposure_usdt=Decimal("500")`，`max_open_positions=2`，`max_daily_loss_pct=Decimal("5")`，`max_consecutive_losses=3`，`max_data_staleness_s=10.0`，`trading_enabled=True`。

`StrategyConfig`：`entry_threshold=0.6`，`exit_threshold=0.4`，`base_notional_usdt=Decimal("100")`，`cooldown_s=900`，`stop_loss_pct=Decimal("0.01")`，`take_profit_pct=Decimal("0.02")`，`max_hold_s=14400`，`signal_half_life_s=1800`，`detector_weights={"funding_extreme":0.5,"liquidation_burst":0.7,"news_sentiment":1.0}`。

`DetectorConfig`：`funding_annualized_threshold=Decimal("0.30")`，`liquidation_window_s=300`，`liquidation_notional_threshold_usdt=Decimal("50000")`，`liquidation_cooldown_s=900`，`news_min_confidence=0.6`。

`NewsConfig`：`rss_feeds=["https://www.coindesk.com/arc/outboundfeeds/rss/","https://cointelegraph.com/rss"]`，`rss_poll_interval_s=300`，`x_bearer_token: SecretStr | None=None`，`x_query="(from:binance OR from:cz_binance OR from:coinbase OR from:SECGov OR from:federalreserve) -is:retweet"`，`x_poll_interval_s=120`，`x_max_results=10`，`x_daily_read_budget=2000`。

`LLMConfig`：`enabled=True`，`provider: Literal["deepseek","none"]="deepseek"`，`model="deepseek-chat"`，`base_url="https://api.deepseek.com"`，`daily_call_budget=500`，`max_text_chars=4000`，`timeout_s=30.0`。

`StrategyConfig` 与 `DetectorConfig` 是可变模型：AutoTuner（5.12）会在运行时修改它们，因此所有使用方必须在调用时读取字段，不得在构造时缓存。

### 5.2 `ai_trader/models.py`（pydantic v2，`frozen=True`）

枚举：`Direction{BULLISH,BEARISH,NEUTRAL}`、`Side{BUY,SELL}`、`PositionSide{LONG,SHORT,FLAT}`、`OrderType{MARKET,LIMIT,STOP_MARKET,TAKE_PROFIT_MARKET}`、`OrderStatus{NEW,PARTIALLY_FILLED,FILLED,CANCELED,REJECTED,EXPIRED,EXPIRED_IN_MATCH}`、`Horizon{MINUTES,HOURS,DAYS}`、`Intent{OPEN,CLOSE}`、`OrderRole{ENTRY,STOP_LOSS,TAKE_PROFIT,CLOSE}`。枚举值为字符串、与币安字面一致（`Direction`/`Horizon`/`Intent`/`OrderRole` 为小写）。

模型（字段名即接口）：

- `MarkPrice(symbol, mark_price: Decimal, index_price: Decimal, funding_rate: Decimal, next_funding_time: datetime, event_time: datetime)`
- `Kline(symbol, interval, open_time, close_time, open, high, low, close, volume: Decimal, is_closed: bool)`
- `Liquidation(symbol, side: Side, price: Decimal, qty: Decimal, event_time)`；`notional` 属性 = price × qty；`side == SELL` 表示多头被清算。
- `NewsItem(id: str, source: str, author: str | None, title: str, text: str, url: str | None, published_at, fetched_at, raw: dict = {})`
- `Sentiment(direction: Direction, confidence: float, symbols: list[str], horizon: Horizon, rationale: str, model: str)`
- `Signal(id: str, detector: str, symbol: str, direction: Direction, strength: float, created_at, expires_at, ref_price: Decimal, rationale: str, meta: dict = {})`；`signed_strength` 属性：BULLISH → +strength，BEARISH → −strength，NEUTRAL → 0。
- `Decision(id, symbol, side: Side, intent: Intent, notional_usdt: Decimal, score: float, signal_ids: list[str], created_at, stop_loss_pct: Decimal, take_profit_pct: Decimal, max_hold_s: int)`
- `RiskVerdict(approved: bool, reason: str | None = None, adjusted_notional: Decimal | None = None)`
- `OrderRequest(symbol, side, type: OrderType, quantity: Decimal | None = None, price: Decimal | None = None, stop_price: Decimal | None = None, reduce_only: bool = False, close_position: bool = False, client_order_id: str, time_in_force: str | None = None)`
- `OrderResult(order_id: int, client_order_id: str, symbol, side, type: OrderType, status: OrderStatus, orig_qty: Decimal, executed_qty: Decimal, avg_price: Decimal, stop_price: Decimal | None, reduce_only: bool, close_position: bool, update_time: datetime)`
- `OrderRecord(client_order_id, decision_id: str | None, symbol, side, type, role: OrderRole, qty: Decimal | None, price, stop_price, reduce_only, close_position, status: OrderStatus, order_id: int | None, avg_price: Decimal, executed_qty: Decimal, created_at, updated_at)`
- `Fill(order_id: int, client_order_id: str, symbol, side, price: Decimal, qty: Decimal, realized_pnl: Decimal, commission: Decimal, event_time)`
- `Position(symbol, side: PositionSide, quantity: Decimal (绝对值), entry_price: Decimal, mark_price: Decimal, unrealized_pnl: Decimal, leverage: int, liquidation_price: Decimal | None)`；`notional` 属性 = quantity × mark_price。
- `AccountState(total_wallet_balance: Decimal, available_balance: Decimal, total_unrealized_pnl: Decimal, positions: list[Position], updated_at)`；`open_positions()` 返回 quantity > 0 的持仓。
- 事件：`DataStale(symbol: str, age_s: float)`、`DataFresh(symbol: str)`、`ReconcileMismatch(symbol, local_qty: Decimal, remote_qty: Decimal)`、`KillSwitchTriggered(reason: str)`、`AccountUpdate(state: AccountState)`。

工具：`utc_now() -> datetime`、`new_id() -> str`（`uuid4().hex`）、`new_client_order_id() -> str`（`"ait-" + uuid4().hex[:28]`，32 字符，符合币安 `^[\.A-Z\:/a-z0-9_-]{1,36}$`）。

### 5.3 `ai_trader/bus.py`

```python
class EventBus:
    def subscribe(self, event_type: type[T], handler: Callable[[T], Awaitable[None]], *, maxsize: int = 10_000) -> None
    def publish(self, event: object) -> None          # put_nowait 到每个匹配订阅者的队列；满则丢最旧并计数
    async def start(self) -> None                     # 每个订阅一个 worker task
    async def stop(self) -> None
    async def drain(self, timeout_s: float = 2.0) -> None   # 等所有队列清空且 handler 空闲（测试用）
    dropped: dict[str, int]                           # key=f"{event_type.__name__}:{handler.__qualname__}"
```
handler 抛异常只记日志，不影响其他订阅者。订阅按 `isinstance` 匹配（订阅基类可收子类）。

### 5.4 `ai_trader/exchange/binance/`

`errors.py`：`BinanceError(Exception)` ← `BinanceAPIError(status: int, code: int, msg: str)`、`BinanceRateLimitError(BinanceAPIError, retry_after_s: float | None)`、`BinanceConnectionError`、`FilterViolation(ValueError)`、`UnknownSymbol(KeyError)`。

`filters.py`：

```python
@dataclass(frozen=True)
class SymbolFilters:
    symbol: str; tick_size: Decimal; step_size: Decimal; min_qty: Decimal; max_qty: Decimal
    min_notional: Decimal; price_precision: int; quantity_precision: int
    def round_price(self, price: Decimal) -> Decimal            # 向下取到 tick
    def round_qty(self, qty: Decimal) -> Decimal                # 向下取到 step
    def qty_for_notional(self, notional: Decimal, price: Decimal) -> Decimal   # 不满足 min_qty / min_notional → FilterViolation
    def validate(self, req: OrderRequest) -> None               # 数量/价格未对齐、低于最小值 → FilterViolation
class ExchangeInfo:
    symbols: dict[str, SymbolFilters]
    def filters_for(self, symbol: str) -> SymbolFilters         # 缺失 → UnknownSymbol
```

`parsers.py`（纯函数，输入币安原始 dict/list）：`parse_mark_price`、`parse_kline`（WS）、`parse_force_order`、`parse_order_trade_update -> tuple[OrderResult, Fill | None]`（`x == "TRADE"` 且 `l > 0` 时产出 Fill）、`parse_account_update -> AccountUpdate`、`parse_rest_kline(row: list) -> Kline`、`parse_rest_premium_index`、`parse_rest_order`、`parse_rest_position`（`positionAmt` 的符号决定 LONG/SHORT，0 → FLAT）、`parse_rest_account`、`parse_exchange_info`（只保留 `contractType == "PERPETUAL"` 且 `status == "TRADING"`，`MIN_NOTIONAL` 过滤器字段名为 `notional`）。

`rest.py`：

```python
class BinanceFuturesRest:
    def __init__(self, base_url: str, api_key: str | None = None, api_secret: str | None = None, *,
                 recv_window_ms: int = 5000, timeout_s: float = 10.0,
                 http: httpx.AsyncClient | None = None, clock: Callable[[], float] = time.time)
    time_offset_ms: int
    async def aclose(self) -> None
    def sign(self, query: str) -> str                           # HMAC-SHA256(secret, query).hexdigest()
    async def ping(self) -> None                                # GET /fapi/v1/ping
    async def server_time(self) -> int                          # GET /fapi/v1/time
    async def sync_time(self) -> int                            # 设置并返回 time_offset_ms
    async def exchange_info(self) -> ExchangeInfo               # GET /fapi/v1/exchangeInfo
    async def premium_index(self, symbol: str) -> MarkPrice     # GET /fapi/v1/premiumIndex
    async def klines(self, symbol, interval, limit=500, start_time=None, end_time=None) -> list[Kline]
    async def open_interest(self, symbol: str) -> Decimal       # GET /fapi/v1/openInterest
    async def account(self) -> AccountState                     # GET /fapi/v2/account（签名）
    async def position_risk(self, symbol: str | None = None) -> list[Position]   # GET /fapi/v2/positionRisk
    async def set_leverage(self, symbol: str, leverage: int) -> int              # POST /fapi/v1/leverage
    async def set_margin_type(self, symbol: str, margin_type: str) -> None       # POST /fapi/v1/marginType；code -4046 视为成功
    async def place_order(self, req: OrderRequest) -> OrderResult                # POST /fapi/v1/order；不自动重试
    async def get_order(self, symbol, *, client_order_id=None, order_id=None) -> OrderResult
    async def cancel_order(self, symbol, *, client_order_id=None, order_id=None) -> OrderResult
    async def cancel_all_orders(self, symbol: str) -> None                       # DELETE /fapi/v1/allOpenOrders
    async def open_orders(self, symbol: str | None = None) -> list[OrderResult]
    async def create_listen_key(self) -> str                                     # POST /fapi/v1/listenKey
    async def keepalive_listen_key(self) -> None                                 # PUT
    async def close_listen_key(self) -> None                                     # DELETE
```
规则：签名请求参数追加 `timestamp=(clock()*1000 + time_offset_ms)` 与 `recvWindow`，`signature` 放在查询串最后；头 `X-MBX-APIKEY`。非 2xx → 解析 `{"code","msg"}` 抛 `BinanceAPIError`；429/418 → `BinanceRateLimitError`（读 `Retry-After`）；`httpx.TransportError` → `BinanceConnectionError`。GET 请求对连接错误和 5xx 最多重试 3 次（退避 0.5/1/2 s）；POST/DELETE 不重试。`place_order` 参数映射：`symbol, side, type, quantity, price, stopPrice, reduceOnly, closePosition, newClientOrderId, timeInForce（LIMIT 默认 GTC）, workingType=MARK_PRICE（止损/止盈单）, newOrderRespType=RESULT`；布尔用 `"true"/"false"`，Decimal 用 `format(x, "f")`。日志只记路径和状态码，不记查询串。

`ws.py`：

```python
def market_stream_url(base_ws: str, streams: Sequence[str]) -> str   # f"{base_ws}/stream?streams=" + "/".join(streams)
def user_stream_url(base_ws: str, listen_key: str) -> str          # f"{base_ws}/ws/{listen_key}"
class BinanceFuturesWS:
    def __init__(self, url: str, handler: Callable[[dict], Awaitable[None]], *,
                 backoff_s: Sequence[float] = (1, 2, 5, 10, 30), connect=websockets.connect, clock=time.monotonic)
    last_message_at: float | None; reconnects: int
    async def run(self) -> None      # 连接→收消息→handler(msg.get("data", msg))；断开按 backoff 重连直到 stop()
    async def stop(self) -> None
```

### 5.5 `ai_trader/data/`

`market_state.py`：`MarketState.update_mark(mp)`, `.mark(symbol) -> MarkPrice | None`, `.age_s(symbol, now=None) -> float | None`（基于 monotonic 时钟）。

`market_feed.py`：`build_stream_names(symbols, kline_intervals=("1m",)) -> list[str]`（`btcusdt@markPrice@1s`, `btcusdt@kline_1m`, `btcusdt@forceOrder`）；`MarketFeed(bus, state, ws_url, symbols, *, ws_factory=None)` 的 `handle(msg)` 按 `msg["e"]` 分发并 publish；`run()/stop()`。`StalenessWatchdog(bus, state, symbols, max_age_s, *, check_interval_s=1.0, clock)`：超龄首次发 `DataStale`，恢复时发 `DataFresh`；`is_stale(symbol)`。`MarkPriceSampler(bus, store, interval_s=10)`：订阅 `MarkPrice`，每 symbol 最多每 interval 写一条样本。

`news/base.py`：`class NewsSource(Protocol): name: str; async def fetch(self) -> list[NewsItem]`。`DailyBudget(limit: int, clock=time.time)`：`try_consume(n=1) -> bool`、`remaining`、UTC 日切重置。
`news/rss.py`：`RssSource(name, url, http: httpx.AsyncClient)`；`id = sha1(entry.id or entry.link)`。
`news/x_api.py`：`XSearchSource(bearer_token, query, http, budget: DailyBudget, *, max_results=10)`；`GET https://api.x.com/2/tweets/search/recent` 参数 `query, max_results, since_id, tweet.fields=created_at,author_id,public_metrics, expansions=author_id, user.fields=username`；维护 `since_id`；预算不足返回 `[]` 并仅告警一次；429 → 返回 `[]` 并把下次允许时间推到 `x-rate-limit-reset`。`id = f"x:{tweet_id}"`，`source="x"`，`author=username`。
`news/poller.py`：`NewsPoller(bus, store, sources: Sequence[tuple[NewsSource, int]])`：按各自间隔循环，`store.insert_news` 返回 True 的才 publish。

### 5.6 `ai_trader/analysis/`

`sentiment/base.py`：`class SentimentClassifier(Protocol): name: str; async def classify(self, item: NewsItem) -> Sentiment`。`canonical_symbols(raw: Iterable[str], universe) -> list[str]`（`"BTC"`/`"btc"`/`"BTCUSDT"` → `"BTCUSDT"`，未知丢弃）。
`sentiment/keyword.py`：`KeywordClassifier(universe)`，内置利多/利空词表（中英文）与币种词 → 符号映射；confidence 0.3（1 词）~0.6（≥3 词）；无命中 → NEUTRAL 0.0。
`sentiment/deepseek.py`：`SentimentOutput(BaseModel)`（direction/confidence/symbols/horizon/rationale）；`DeepSeekClassifier(http: httpx.AsyncClient, api_key: str, universe, *, model="deepseek-chat", base_url="https://api.deepseek.com", fallback: SentimentClassifier, budget: DailyBudget, max_text_chars=4000, timeout_s=30.0)`，`name = model`。请求：`POST {base_url}/chat/completions`，头 `Authorization: Bearer <key>`，体 `{"model", "temperature": 0, "max_tokens": 512, "response_format": {"type": "json_object"}, "messages": [{"role":"system","content":SYSTEM},{"role":"user","content":user_text}]}`（SYSTEM 必须含 "json" 字样并列出符号 universe）。`choices[0].message.content` 经 `SentimentOutput.model_validate_json` 解析；预算耗尽、非 2xx、`httpx.HTTPError`、非法 JSON/校验失败 → `fallback.classify(item)`，结果 `model="keyword-fallback"`；成功 → `canonical_symbols`，`model=<model>`。日志不得包含 key。
`detectors/base.py`：`class Detector(Protocol): name: str; subscribes_to: tuple[type, ...]; async def on_event(self, event) -> list[Signal]`；`DetectorRunner(bus, store, detectors)`：为每个探测器订阅其事件类型，产出的 Signal 先 `store.insert_signal` 再 `bus.publish`。
`detectors/funding_extreme.py`：年化 = `funding_rate × 3 × 365`；|年化| ≥ 阈值 → 正为 BEARISH、负为 BULLISH，`strength = min(1, |年化| / (2×阈值))`，每 `(symbol, next_funding_time)` 只发一次，`expires_at = next_funding_time`。
`detectors/liquidation_burst.py`：滑动窗口内 `SELL` 侧清算名义和 ≥ 阈值 → BULLISH；`BUY` 侧 → BEARISH；`strength = min(1, 和/(2×阈值))`；`expires_at = now + 15 min`；每 symbol 冷却 `liquidation_cooldown_s`。
`detectors/news_sentiment.py`：`NewsSentimentDetector(classifier, universe, store, state, cfg: DetectorConfig | None = None, *, min_confidence: float | None = None)`（阈值每次调用时读取：显式 `min_confidence` 优先，否则 `cfg.news_min_confidence`）：分类 → `store.insert_sentiment` → 每个命中符号一条 Signal（`strength = confidence`；horizon → 过期：minutes 30 min、hours 4 h、days 24 h）；NEUTRAL 或 confidence < min → 不发。

### 5.7 `ai_trader/strategy/aggregator.py`

`SignalAggregator(bus, store, state, cfg: StrategyConfig, positions: Callable[[], Mapping[str, Position]], clock=time.time)`：

- `score(symbol, now=None) -> float = Σ signed_strength × weight[detector] × 0.5^(age/half_life)`，只算未过期信号。
- `on_signal(s)`：无持仓且 |score| ≥ `entry_threshold` 且距上次决策 ≥ `cooldown_s` → `Decision(intent=OPEN, side=BUY if score>0 else SELL, notional=base_notional × min(1,|score|))`；有持仓且 score 反向超过 `exit_threshold` → `Decision(intent=CLOSE, side=反向, notional=持仓名义)`。决策先 `store.insert_decision` 再 publish。

### 5.8 `ai_trader/risk/`

`engine.py`：`RiskEngine(limits, store, state, allowed_symbols, *, clock)`，`evaluate(d: Decision, account: AccountState) -> RiskVerdict`，依次检查并以首个失败为 `reason`：`kill_switch`（kv `kill_switch == "1"`）→ `trading_disabled` → `symbol_not_allowed` → `data_stale`（`state.age_s > max_data_staleness_s` 或无数据）。只有 `kill_switch` 同时拦截 CLOSE：`intent == CLOSE` 只要杀开关未激活即批准——减仓不得被交易开关、symbol 白名单或陈旧行情卡住；`trading_disabled`、`symbol_not_allowed`、`data_stale` 仅拦截 OPEN。OPEN 继续：名义 > `max_order_notional_usdt` → 不拒绝，`adjusted_notional = max_order_notional_usdt`；`总敞口 + 名义 > max_total_exposure_usdt` → `max_total_exposure`；`len(open_positions) ≥ max_open_positions` → `max_open_positions`；当日已实现盈亏 ≤ −`max_daily_loss_pct`% × 当日起始权益（kv `day_start_equity:{UTC日期}`，首次评估时写入 `total_wallet_balance`）→ `daily_loss_limit`（当日起始权益 ≤ 0 时跳过此项并每日记一次日志，而不是拒绝一切）；`store.consecutive_losses() ≥ max_consecutive_losses` → `consecutive_losses`。每次裁决 `store.insert_risk_verdict`。
`kill_switch.py`：`KillSwitch(store, broker, bus)`：`trigger(reason)` → `set_kv("kill_switch","1")`、对每个有持仓或挂单的 symbol `cancel_all` + `close_position`、publish `KillSwitchTriggered`；`is_active()`；`reset()`。

### 5.9 `ai_trader/execution/`

`broker.py`：

```python
class Broker(Protocol):
    exchange_info: ExchangeInfo
    async def start(self) -> None; async def stop(self) -> None
    async def account(self) -> AccountState
    async def positions(self) -> dict[str, Position]              # 只含 quantity > 0
    async def ensure_symbol_setup(self, symbol: str, leverage: int, margin_type: str) -> None
    async def submit(self, req: OrderRequest) -> OrderResult
    async def cancel(self, symbol: str, client_order_id: str) -> OrderResult
    async def cancel_all(self, symbol: str) -> None
    async def close_position(self, symbol: str) -> OrderResult | None   # reduce_only MARKET 反向全平；无仓返回 None
```
`paper.py`：`PaperBroker(state, bus, exchange_info, *, initial_balance=Decimal("10000"), fee_rate=Decimal("0.0004"), slippage_bps=2, clock)`：MARKET 立即按标记价 ±滑点成交并 publish `Fill`；`STOP_MARKET`/`TAKE_PROFIT_MARKET` 挂起，订阅 `MarkPrice` 触发（`closePosition=True` 时全平）；维护余额、持仓、已实现盈亏（含手续费）。
`binance.py`：`BinanceFuturesBroker(rest, exchange_info, bus, ws_url, *, ws_factory=None, reconcile_interval_s=60, on_mismatch: Literal["log","kill"]="kill", kill: Callable[[str], Awaitable[None]] | None = None, clock)`：`submit` 先 `filters.validate`；`httpx.TimeoutException`/`BinanceConnectionError` 后先 `get_order(client_order_id)`，查到即返回，查不到才抛；`start()` 建 listenKey、起用户数据流（`ORDER_TRADE_UPDATE` → publish `OrderResult` 与 `Fill`；`ACCOUNT_UPDATE` → 更新本地持仓缓存并 publish `AccountUpdate`）、每 30 min keepalive；`reconcile()` 每 `reconcile_interval_s` 用 `position_risk` 比对本地缓存，不一致 publish `ReconcileMismatch`，`on_mismatch == "kill"` 时调用 `kill(reason)`。
`service.py`：`ExecutionService(bus, broker, risk, store, settings, clock)`：订阅 `Decision`：`risk.evaluate` → 未批准仅落库；批准 OPEN → `ensure_symbol_setup` → `qty = filters.qty_for_notional(名义, mark)` → MARKET 入场 → 成交后以 `avg_price × (1 ∓ stop_loss_pct)`、`(1 ± take_profit_pct)` 下 `STOP_MARKET`/`TAKE_PROFIT_MARKET`（`close_position=True`，价格按 tick 取整），三张单都 `store.upsert_order`（role 分别为 ENTRY/STOP_LOSS/TAKE_PROFIT）；批准 CLOSE → `cancel_all(symbol)` + `close_position(symbol)`（role CLOSE）。订阅 `Fill`/`OrderResult` → `store.insert_fill` / 更新订单状态；某保护单成交后取消同 symbol 另一张。`enforce_max_hold()` 每 60 s：持仓持有时间 > `max_hold_s` → 发 CLOSE 决策。

### 5.10 `ai_trader/storage/db.py`

`Store(path)`：`open()/close()`；表：`news`、`sentiments`、`signals`、`forward_returns(signal_id, horizon_s, ret, computed_at, PK(signal_id,horizon_s))`、`mark_samples(symbol, ts, price)`、`decisions`、`risk_verdicts`、`orders`、`fills`、`kv`。方法：`news_exists`、`insert_news -> bool`、`insert_sentiment`、`insert_signal`、`recent_signals(limit)`、`signals_missing_forward_return(horizon_s, before) -> list[Signal]`、`insert_forward_return`、`effectiveness() -> list[EffectivenessRow(detector, horizon_s, n, mean_ret, hit_rate)]`、`insert_mark_sample`、`mark_at(symbol, ts, tolerance_s=60) -> Decimal | None`、`insert_decision`、`insert_risk_verdict`、`upsert_order`、`get_order`、`open_protective_orders(symbol)`、`update_order_status(client_order_id, status, executed_qty, avg_price, order_id)`、`insert_fill`、`realized_pnl_since(since) -> Decimal`、`consecutive_losses() -> int`（按 event_time 倒序取 `realized_pnl != 0` 的成交，数连续 < 0 的个数）、`last_decision_at(symbol)`、`get_kv/set_kv`。

`ai_trader/analysis/forward_returns.py`：`ForwardReturnTracker(store, state, *, horizons_s=(600, 3600, 14400), interval_s=60, clock)`：对每个 horizon 取 `signals_missing_forward_return(h, now−h)`，价格取 `store.mark_at(symbol, created_at + h)`，缺失则跳过；`ret = (p1 − ref)/ref × sign(direction)`。

### 5.11 `ai_trader/app.py` 与 `ai_trader/cli.py`

`async create_components(settings, *, rest=None, ws_factory=None, http=None, store=None) -> Components`（内部 `await rest.exchange_info()`；`http` 为 RSS/X/DeepSeek 共用客户端）（dataclass，持有全部组件，便于测试注入）；`App(components).run()`：`store.open` → `bus.start` → `broker.start` → 启动 feed/watchdog/sampler/poller/aggregator/execution/tracker/reconcile 任务 → 每 60 s 健康日志（WS 年龄、信号数、持仓、杀开关）→ SIGINT/SIGTERM 优雅停止（反序停、关 listenKey、关 DB）。每个长期组件由监督器运行：抛出 `Exception` 时记录并按 1/2/5/10/30 s 退避重启，单个组件崩溃不得终止进程。

CLI（typer，脚本名 `ai-trader`）：`tuning`（最近 50 条自动调参记录）、`probe`（ping、服务器时间与本地偏移、合约数、各 symbol 标记价与年化资金费；有 key 时打印余额）、`run [--mode paper|live] [--confirm-mainnet]`（`binance_testnet=False` 且无 `--confirm-mainnet` → 退出码 2 并说明）、`kill`、`status`（持仓、挂单、当日已实现盈亏、杀开关、最近 10 条信号）、`signals`（有效性表）、`classify TEXT`（有 Anthropic 凭据用 Claude，否则关键词）。

### 5.12 `ai_trader/strategy/autotune.py`（**[用户要求 2026-10-29 深夜]**："如果结果出现偏差，或者实测数据不好，你需要自动调整策略"）

`AutoTuner(store, strategy_cfg: StrategyConfig, detector_cfg: DetectorConfig, *, interval_s=1800, activity_window_s=7200, clock)`：每 `interval_s` 执行 `tick()`，按顺序评估四条规则，每条每次最多一步，所有改动写入 `tuning_log(ts, rule, field, old, new, reason)` 并打日志；**绝不修改 `RiskLimits`**：

1. `activity_floor`：窗口内信号 < 3 且决策 == 0 → 清算阈值 ×0.7（≥5000）、新闻置信度阈值 −0.05（≥0.3）、资金费率阈值 ×0.8（≥0.05）、`entry_threshold` −0.05（≥0.3）。
2. `detector_quality`：1 h 前瞻收益样本 n ≥ 20 的探测器，命中率 < 0.40 且均值 < 0 → 权重 −0.25（≥0，0 即停用）；命中率 ≥ 0.55 且均值 > 0 → 权重 +0.1（≤1.5）。
3. `loss_brake`：当日已实现亏损 ≤ −2% 起始权益 → `base_notional_usdt` ×0.5（≥20）且 `entry_threshold` +0.1（≤0.9）；当日 ≥ +2% 且名义低于默认 → ×1.25 回升（≤100）。
4. `overtrading_brake`：窗口内决策 ≥ 10 → `cooldown_s` ×1.5（≤3600）且 `entry_threshold` +0.05（≤0.9）。

模型 `TuningChange(ts, rule, field, old, new, reason)`；`Store` 新增 `insert_tuning_change`、`tuning_log(limit)`、`count_signals_since(ts)`、`count_decisions_since(ts)`；CLI `tuning` 与 `status` 展示当前生效参数。

## 6. 测试策略

- 单元测试：`pytest -q`，`asyncio_mode=auto`；HTTP 用 `respx` 模拟；WS 用 `websockets.serve` 起本机回环假服务器；时钟全部注入。
- 固件：币安官方文档消息样例 + 2026-10-29 测试网实录消息，放 `tests/fixtures/binance/*.json`。
- 集成测试 `tests/integration/`，标记 `integration`，仅在设置 `BINANCE_API_KEY`/`BINANCE_API_SECRET` 时运行：probe、下一张远离市价的 LIMIT 单再撤单、读取持仓。
- 公网只读冒烟标记 `network`，仅在 `AIT_NETWORK_TESTS=1` 时运行。
- 收尾验收：`ai-trader probe` 实打测试网；`ai-trader run --mode paper` 跑 2 分钟，确认 `mark_samples`、`signals`（如有）入库且无异常退出。

## 7. 留给实施者的决定

- 日志格式细节、异常消息文案。
- `KeywordClassifier` 的具体词表（但必须覆盖：ETF、SEC、hack/exploit、listing/delist、halving、rate hike/cut、liquidation、bankruptcy；中文：上市、下架、黑客、加息、降息、破产、利好、利空）。
- SQLite 索引选择；pydantic 与 sqlite 之间的序列化辅助。
- 健康日志的字段排版。

## 8. 对结果的预期（写给用户）

这套系统能在测试网完整运转，并把每个信号的 10 分钟 / 1 小时 / 4 小时前瞻收益存下来。它不保证有正期望：调研结论是公开信息驱动的方向交易扣费后接近零。正确的用法是先跑一个月 `paper`/`live`（测试网），每周看 `ai-trader signals`，只保留命中率和均值都站得住的探测器，再考虑主网小额。X 和 Claude 的每日预算默认很保守（约 10 美元 + 几美元/天），可按需放开。
