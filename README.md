# ai_trader — 币安 USDT 本位合约事件驱动交易系统（测试网优先）

单进程 asyncio 守护进程：实时行情（WS）+ RSS/X 新闻 → 利好/利空判断 → 探测器产生信号 → 信号聚合 → 风控 →
下单（模拟盘或测试网/主网）→ 成交回报 → 对账，并把每个信号的前瞻收益存库，供人工/自动调参依据。

设计稿：`docs/superpowers/specs/2026-10-29-futures-testnet-design.md`（下文简称“设计稿”）。

## 预期与提醒

> 这套系统能在测试网完整运转，并把每个信号的 10 分钟 / 1 小时 / 4 小时前瞻收益存下来。**它不保证有正期望**：
> 调研结论是公开信息驱动的方向交易扣费后接近零。正确的用法是先跑一个月 `paper`/`live`（测试网），每周看
> `ai-trader signals`，只保留命中率和均值都站得住的探测器，再考虑主网小额。X 和 DeepSeek 的每日预算默认
> 很保守（约 10 美元 + 几美元/天），可按需放开。
>
> —— 设计稿第 8 节

简言之：**这是一套信号质量测量工具，不是“自动赚钱机器”**。在考虑接入主网真实资金前，至少让它在测试网/
paper 模式跑满 **一个月**，用 `ai-trader signals` 的实测命中率和均值收益做决定。

## 本地网络限制与测试网说明

2026-10-29 实测（本机环境）：

| 端点 | 状态 |
|---|---|
| `https://testnet.binancefuture.com`（REST） | 可达，约 0.5 s；`ai-trader probe` 打印 570 个交易中的永续合约（exchangeInfo 原始 743 个条目，过滤掉非 PERPETUAL / 非 TRADING 的） |
| `wss://stream.binancefuture.com`（WS） | 可达，`markPrice`/`aggTrade`/`forceOrder` 均有推送 |
| `https://fapi.binance.com`、`wss://fstream.binance.com`（主网） | 不可达（DNS 劫持/超时） |
| `https://demo-fapi.binance.com`（Demo Trading） | 不可达 |
| `https://www.binance.com/...`（公告等） | 不可达 |
| DeepSeek（`https://api.deepseek.com`） | 可达 |
| X API v2 | 可达，但 2026-09 起**仅按量付费**：读 1 条约 0.005 美元，无免费层 |

因此：

- **所有默认值指向测试网**。日常开发、paper 模式、集成测试都在测试网上进行，无需任何特殊网络环境。
- 主网（`fapi.binance.com` / `fstream.binance.com`）和 Demo Trading（`demo-fapi.binance.com`）域名在本机不可达，
  **必须在海外服务器或代理环境下才能使用**，本地只能验证测试网路径。
- X API 是按量付费服务，`NEWS__X_DAILY_READ_BUDGET`（默认 2000 条/天，约 10 美元上限）控制每日读取量上限，
  用完当天自动停止读取并只告警一次。
- DeepSeek 分类器有独立的每日调用预算 `LLM__DAILY_CALL_BUDGET`（默认 500），超预算或任何失败都会**自动退化**
  为内置关键词分类器，不会让系统停摆。

## 快速开始

```bash
uv sync --group dev                 # 安装依赖（含测试/lint 工具）
cp .env.example .env                # 复制环境样例，按需填写（至少测试网 BINANCE_API_KEY/SECRET）
uv run ai-trader probe              # 验证连通性：ping、服务器时间偏移、合约数、标记价/资金费率
uv run ai-trader run --mode paper   # 真实测试网行情 + 模拟成交，Ctrl+C 优雅停止
uv run ai-trader run --mode live    # 真实下单（测试网，除非显式切到主网），见下方「主网启用步骤」
```

`paper` 模式用真实的测试网行情驱动一个本地模拟经纪商（初始资金 10000 USDT，含手续费与滑点模拟），
不会向交易所下任何真实订单，适合长期挂机验证信号质量。

## CLI 一览

脚本名 `ai-trader`（即 `uv run ai-trader <command>`）：

| 命令 | 作用 |
|---|---|
| `version` | 打印版本号 |
| `probe` | 检查与配置端点的连通性（ping、服务器时间偏移、合约数、各 symbol 标记价与年化资金费率；有 key 时打印余额） |
| `classify TEXT` | 把 `TEXT` 当作一条新闻，跑一遍情绪分类器（有 `DEEPSEEK_API_KEY` 用 DeepSeek，否则用关键词兜底），打印 JSON |
| `run [--mode paper\|live] [--confirm-mainnet]` | 启动交易守护进程直到被中断；`--mode` 覆盖 `.env` 里的 `MODE`；只要 REST/WS 端点不是测试网域名（`testnet.binancefuture.com` / `stream.binancefuture.com`）就必须加 `--confirm-mainnet`（不论 `BINANCE_TESTNET` 取值，`BINANCE_REST_URL`/`BINANCE_WS_URL` 覆盖同样适用），否则退出码 2；`LEVERAGE` 大于 `RISK__MAX_LEVERAGE` 时拒绝启动 |
| `kill [--reset]` | 设置持久化杀开关（kv `kill_switch=1`）；live 模式下本命令同时撤销所有挂单并平掉所有持仓（任何 symbol 撤单/平仓失败都会逐条打印并以退出码 1 结束）；正在运行的守护进程（paper 或 live）在 ~15 s 内观察到该标志并对自己的 broker 执行一次全平。`--reset` 清除杀开关（kv `kill_switch=0`）并打印新状态 |
| `stop` | 请求正在运行的守护进程优雅退出（kv `stop_requested=1`），守护进程在 ~15 s 内停止并把标志复位为 0 |
| `status` | 打印杀开关状态、当日已实现盈亏、各表计数、当前生效的自动调参参数、最近 10 条信号；paper 模式打印模拟账户，live 模式打印真实持仓/挂单。注意两行盈亏口径不同：`realized PnL today (UTC, from fills, gross of fees)` 是当日成交回报的已实现盈亏之和，**未扣手续费**；`paper account (persisted, net of fees)` 的 `wallet`/`realized_pnl` 是模拟账户口径，**已扣手续费** |
| `signals` | 打印信号有效性表（按探测器 × 前瞻窗口的样本数、均值收益、命中率） |
| `tuning` | 打印最近 50 条 AutoTuner 自动调参记录 |
| `dashboard [--host 127.0.0.1] [--port 8787]` | 启动只读的本地实时网页面板（见下方「实时面板」），打印地址后一直运行到 Ctrl+C |

## 架构

```
                 ┌──────────────────────── EventBus（按类型订阅，每订阅者独立队列）────────────────────────┐
                 │                                                                                           │
 Binance WS ──► MarketFeed ──► MarkPrice / Kline / Liquidation ──► FundingExtremeDetector ─┐                 │
   (testnet)       │                                             LiquidationBurstDetector ─┤                 │
                   └─► MarketState（最新标记价、新鲜度）         NewsSentimentDetector ────┼─► Signal ──► SignalAggregator ──► Decision
 RSS / X API ──► NewsPoller ──► NewsItem ──► DeepSeekClassifier(→KeywordClassifier 兜底) ──┘       │                         │
                                                                                                 Store(SQLite)        RiskEngine ──► RiskVerdict
 StalenessWatchdog ──► DataStale / DataFresh                                                                                │
 KillSwitch ──► KillSwitchTriggered                                                                             ExecutionService
 ForwardReturnTracker（信号前瞻收益 10m/1h/4h）                                                                        │
                                                                                                  Broker 接口：PaperBroker | BinanceFuturesBroker
                                                                                                                 │  用户数据流 Fill / 持仓更新 ──► bus
                                                                                                                 └  每 60 s REST 对账，不一致 → 杀开关
```

所有组件只通过 `EventBus` 和 `Store`（SQLite）耦合；`MarketState` 是唯一的进程内共享状态（最新标记价/新鲜度）。
每个长期运行组件由监督器包裹：单个组件抛异常只记录日志并按 1/2/5/10/30 s 退避重启，不会拖垂整个进程。

## 配置

所有配置来自环境变量 / `.env`（`ai_trader/settings.py`，`pydantic-settings`，嵌套字段用 `__` 分隔）。
完整列表（含全部默认值）见 [`.env.example`](.env.example)；下表是最常用的几组：

| 分组 | 变量前缀 | 控制什么 |
|---|---|---|
| 顶层 | `BINANCE_*`、`SYMBOLS`、`LEVERAGE`、`MARGIN_TYPE`、`MODE`、`DB_PATH`、`LOG_*` | 交易所端点与模式、交易标的、杠杆、存储与日志 |
| `RISK__*` | 风控硬限制 | 最大杠杆/单笔名义/总敞口/持仓数/日亏损率/连续亏损次数/行情新鲜度；**AutoTuner 永不修改这组参数** |
| `STRATEGY__*` | 信号聚合与下单 | 开/平仓阈值、基础下单名义、冷却时间、止损/止盈比例、最大持有时间、信号半衰期、AutoTuner 触发阈值（`OVERTRADING_DECISIONS=10`：窗口内决策数达到即触发 overtrading_brake；`ACTIVITY_MIN_SIGNALS=3`：信号数低于它且无决策即触发 activity_floor；已调过的参数持久化在 kv `tuning_effective`，要回到配置值需先停守护进程、运行 `ai-trader tuning --reset`、再重启）、各探测器权重（默认 `funding_extreme=0.5`、`liquidation_burst=0.7`、`news_sentiment=1.0`（DeepSeek 判断的新闻）、`news_keyword=0.5`（关键词分类器 / DeepSeek 失败兜底判断的新闻，证据较弱，单独计权、单独自动调参）、`breakout=0.8`、`mean_reversion=0.6`） |
| `DETECTORS__*` | 探测器阈值 | 资金费率年化阈值、清算窗口与阈值、新闻置信度阈值；K 线突破（`BREAKOUT_LOOKBACK=60`、`BREAKOUT_VOLUME_MULT=1.5`、`BREAKOUT_MIN_MOVE_PCT=0.15`、`BREAKOUT_TTL_S=1800`、`BREAKOUT_COOLDOWN_S=900`）与均值回归（`MR_LOOKBACK=30`、`MR_Z_ENTRY=2.5`、`MR_TTL_S=1200`、`MR_COOLDOWN_S=900`）参数 |
| `NEWS__*` | 新闻来源 | RSS 源列表与轮询间隔、X 查询与每日读取预算、`NEWS__MAX_NEWS_AGE_S`（默认 7200 s：发布时间早于此的新闻只入库、不分类（不花 DeepSeek 预算）、不产生信号；健康日志里的 `stale_news_skipped` 是计数） |
| `LLM__*` | 情绪分类器 | 是否启用 DeepSeek、模型、每日调用预算、超时 |

`StrategyConfig` 与 `DetectorConfig` 是运行时可变模型：AutoTuner（见下）会在进程运行期间直接修改它们的字段，
所有读取方都必须在调用时取值，不能在启动时缓存一份快照。

## 风控与杀开关

`RiskEngine.evaluate` 依次检查（第一个失败项即拒绝理由）：杀开关 → 交易是否启用 → symbol 是否允许 →
行情是否新鲜 → 单笔名义上限（超限不拒绝，直接调整为上限）→ 总敞口上限 → 最大持仓数 → 当日亏损率上限
（当日起始权益 ≤ 0 时跳过）→ 连续亏损次数上限。**只有杀开关会拦截平仓单**：平仓（CLOSE）是减仓动作，
只要杀开关未激活即批准，不受交易开关、symbol 白名单、行情新鲜度影响，避免这些条件把已有仓位卡住。
每次裁决都落库 `risk_verdicts`。

杀开关（`KillSwitch`）独立于策略：

- `uv run ai-trader kill`：写入持久化标志 `kv.kill_switch=1`，之后任何决策（包括平仓）都会被 `RiskEngine`
  拒绝，最大持有时间检查也不再发平仓决策（全平由杀开关自己负责）。
- live 模式下 `kill` 命令本身会撤销所有挂单并市价平掉所有持仓，失败项逐条打印并以退出码 1 结束。
- 正在运行的守护进程每 15 s 检查一次 kv：看到 `kill_switch=1` 时对进程内的 broker 执行一次
  `KillSwitch.trigger`（paper 模式下模拟仓位就是这样被平掉的），每次激活只执行一次。
- 启动时若 kv 里遗留着 `kill_switch=1`：守护进程**要等所有 symbol 都收到新鲜标记价**（不超过
  `RISK__MAX_DATA_STALENESS_S`）才执行全平，在此之前恢复出来的仓位及其止损/止盈挂单保持不动。某个 symbol
  暂时无法平仓时，该 symbol 的止损/止盈不会被撤销；只要全平没有干净完成（且仍有持仓），下一轮控制检查
  （15 s 后）就会重试。
- `uv run ai-trader kill --reset`：清除杀开关（kv `kill_switch=0`），恢复开仓。
- `uv run ai-trader stop`：写入 kv `stop_requested=1`，守护进程 ~15 s 内优雅退出并把标志复位；启动时若发现
  遗留的 `stop_requested=1` 会先清除，避免一启动就退出。
- `BinanceFuturesBroker` 每 60 s 用真实持仓对账本地缓存，发现不一致时按配置可以自动触发杀开关
  （默认 `on_mismatch="kill"`）。

## X 与 DeepSeek 的成本控制

- X API v2 每读 1 条约 0.005 美元，无免费层：`NEWS__X_DAILY_READ_BUDGET`（默认 2000 条/天，上限约 10 美元/天）
  用尽后当天自动停止读取，只告警一次；`NEWS__X_MAX_RESULTS`（默认 10）、`NEWS__X_POLL_INTERVAL_S`（默认 120 s）
  进一步限制单次抓取量和频率。
- DeepSeek 分类器 `LLM__DAILY_CALL_BUDGET`（默认 500 次/天）控制调用上限；预算耗尽、请求失败、响应非法 JSON
  都会自动退化为内置关键词分类器（`model="keyword-fallback"`），系统不会因为预算或 API 异常而停止判断。
- 两者都可以通过把对应预算调到 0 / 把 `LLM__ENABLED` 设为 `false` 完全关闭付费调用，退化为纯行情探测器 +
  关键词分类。

## 如何新增探测器 / 新闻源

探测器实现 `ai_trader/analysis/detectors/base.py` 里的 `Detector` 协议（`name`、`subscribes_to: tuple[type, ...]`、
`async def on_event(self, event) -> list[Signal]`），在 `src/ai_trader/app.py` 的 `_wire()` 里加入 `detectors` 列表
（`DetectorRunner` 会自动按 `subscribes_to` 订阅并把产出的 `Signal` 落库再发布）；记得在
`STRATEGY__DETECTOR_WEIGHTS` 里给新探测器的名字配一个权重，否则聚合时权重视为 0。

新闻源实现 `ai_trader/data/news/base.py` 里的 `NewsSource` 协议（`name`、`async def fetch(self) -> list[NewsItem]`），
加入 `app.py` 的 `_build_sources()` 返回的 `(source, poll_interval_s)` 列表即可；`NewsPoller` 按各自间隔轮询，
只有 `store.insert_news` 返回 `True`（新 id）的条目才会继续往下发布给分类器和探测器。

## 测试

```bash
uv run pytest -q                              # 单元测试（不碰网络），集成测试默认 skip
uv run ruff check .                           # lint
uv run ai-trader probe                        # 实打测试网连通性

# 需要测试网 BINANCE_API_KEY / BINANCE_API_SECRET 才会真正执行（否则 skip）：
BINANCE_API_KEY=xxx BINANCE_API_SECRET=yyy uv run pytest -q -m integration

# 公网只读冒烟测试（ping + 读取标记价，不需要任何 key）：
AIT_NETWORK_TESTS=1 uv run pytest -q -m network
```

单元测试用 `respx` 模拟 HTTP、本机回环假 WS 服务器、注入时钟，完全不依赖外部网络；集成测试
（`tests/integration/test_testnet.py`）会在测试网账户上真实下一张远离市价的 `LIMIT` 单再撤单，只在显式提供
测试网 key 时运行。

## 跑一整夜的 paper 演练

`scripts/paper_overnight.ps1` 以后台独立进程的方式启动 `ai-trader run --mode paper`，并临时放宽新闻源数量和
探测器阈值（环境变量覆盖，不改动仓库里的保守默认值），方便过夜积累信号样本：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\paper_overnight.ps1
```

输出 `started pid=... log=data\paper-run-<timestamp>.log`，PID 同时写入 `data\paper-run.pid`，日志落在
`data\paper-run-<timestamp>.log` / `.err.log`，数据库是 `data\ai_trader.db`。

停止（优雅退出，推荐）：

```powershell
uv run ai-trader stop       # ~15 s 内退出
```

强制停止（守护进程无响应时）：

```powershell
taskkill /PID (Get-Content data\paper-run.pid) /T /F
```

查看运行状况：

```powershell
uv run ai-trader status     # 杀开关、当日 PnL、模拟账户、最近信号
uv run ai-trader signals    # 各探测器的前瞻收益有效性
uv run ai-trader tuning     # 自动调参改了什么
uv run python scripts/check_run.py .   # 只读探针：进程是否存活、各表计数、最后一条行情样本的延迟
```

`scripts/check_run.py` 是只读的，不会修改 `data/` 下任何内容，可以在运行过程中随时执行。

## 实时面板

`ai-trader dashboard` 起一个只依赖标准库的本地网页（默认 <http://127.0.0.1:8787/>），每 5 秒刷新一次：进程状态
（运行中 / 已停止 / 数据陈旧 > 60 s）、杀开关、钱包与今日/累计盈亏（毛，来自 fills）、各 symbol 近 2 小时标记价
走势、持仓与挂单、最近信号 / 决策（含风控拒绝原因）/ 订单 / 成交、信号有效性、自动调参记录、当前生效参数、
每小时新闻量和守护进程日志末尾。

```powershell
uv run --no-sync ai-trader dashboard --port 8787          # 前台运行，Ctrl+C 停止
powershell -ExecutionPolicy Bypass -File scripts\dashboard.ps1   # 后台运行，PID 写入 data\dashboard.pid
taskkill /PID (Get-Content data\dashboard.pid) /T /F      # 停止后台面板
```

面板**只读**：每个请求单独用 `mode=ro` 打开 `data/ai_trader.db`，另外只读 `data/paper-run.pid` /
`data/paper-run.latest` 和对应日志，不会写数据库，可以在守护进程运行时随时开关。JSON 接口是 `GET /api/state`。
守护进程运行期间请始终带 `--no-sync`（它占用着 venv 里的可执行文件）。默认只绑定 127.0.0.1，不要绑到公网地址。

## 主网启用步骤与警告

> **警告**：主网使用真实资金。本机网络不可达 `fapi.binance.com` / `fstream.binance.com`，**必须先在海外服务器
> 或代理环境验证连通性**，再按以下步骤切换；建议先在测试网 `paper`/`live` 模式跑满一个月，用
> `ai-trader signals` 确认至少一个探测器命中率和均值收益都站得住，才考虑主网小额资金。

1. 在币安申请一个**仅限合约交易、禁止提现**的 API key，并设置 **IP 白名单**。
2. `.env` 里设置 `BINANCE_TESTNET=false`，填入主网 `BINANCE_API_KEY`/`BINANCE_API_SECRET`。
3. 启动时显式加 `--confirm-mainnet`：

   ```bash
   uv run ai-trader run --mode live --confirm-mainnet
   ```

   只要 REST/WS 端点不是测试网域名（不论 `BINANCE_TESTNET` 取值，`BINANCE_REST_URL`/`BINANCE_WS_URL` 覆盖也算），
   不加这个参数时 `ai-trader run` 会直接退出（退出码 2）并打印提醒，防止误操作。
4. 建议先把 `RISK__MAX_ORDER_NOTIONAL_USDT` / `RISK__MAX_TOTAL_EXPOSURE_USDT` 调小到你能接受的真实亏损上限，
   并随时用 `uv run ai-trader kill` 紧急停止。

### 上线前检查清单（live-readiness）

最终代码评审列出的「上 live 之前必须满足」项，逐条确认后再考虑主网：

- [x] **listenKey 生命周期**：收到 `listenKeyExpired` 或 keepalive 失败时自动新建 listenKey、停旧 WS、在新 key 上
  重连；用户数据流 / keepalive / 对账任务由监督器看护，意外退出会记 ERROR 并退避重启；日志不打印 listenKey。
- [x] **持仓模式必须是单向（one-way）**：`live` 启动时查询 `GET /fapi/v1/positionSide/dual`，双向（hedge）模式直接
  拒绝启动。请先在币安合约设置里切到单向持仓。
- [x] **`RISK__MAX_LEVERAGE`**：`LEVERAGE` 大于 `RISK__MAX_LEVERAGE` 时拒绝启动；确认两者都设成你能接受的值。
- [x] **主网保护**：只要端点不是测试网域名，`run` 就必须带 `--confirm-mainnet`（含 URL 覆盖）。
- [ ] **先跑 paper ≥ 1 个月**（再跑测试网 `live`），每周看 `ai-trader signals` / `ai-trader tuning`，只保留命中率和
  均值收益都站得住的探测器；这一项只能靠时间完成。
- [ ] 主网 API key：仅合约交易、禁止提现、IP 白名单；`RISK__*` 调到能承受的真实亏损上限。
