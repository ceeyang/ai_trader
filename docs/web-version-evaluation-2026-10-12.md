# ai_trader 网页版改造后评估

日期：2026-10-12 | 分支：`feature/web-version`（15 个提交，基于 `main` 的 `20f9359`）
范围：改造后的项目质量、现有核心模块的问题、距离接入 Polymarket / Jev 还缺什么、下一步优先级。

---

## 1. 改造做了什么

| 项目 | 内容 |
|---|---|
| 后端 | `src/ai_trader/web/`（585 行）：FastAPI 应用工厂、5 组路由（market / dca / analysis / backtest / config）、3 个服务模块、Pydantic 模型。现有 `core/`、`strategies/` 接口未改。 |
| 前端 | `frontend/`（964 行 TS/TSX）：Vite + React 19 + TypeScript + Tailwind 4，K 线用 lightweight-charts v5（单图四 pane：主图+成交量、RSI、MACD、KDJ）。两个页面：定投计算、技术分析（五组参数、图表、三个结果标签页、预设保存/加载）。 |
| 重构 | 信号组合逻辑从 Tkinter 页面内部类抽成 `core/analysis/signals.py` 的 `SignalConfig` + `get_custom_entry/exit_signals`，Tkinter 页面改为调用它（减少约 110 行）。 |
| 工程 | 切换到 uv（Python 3.12），修掉 pyproject 里导致解析失败的假依赖（`tkinter`、`sqlite3`），依赖分运行时 / dev / ml 三组。 |
| 测试 | pytest 56 个（原来 5 个，且其中 1 个依赖联网）、vitest 10 个、Playwright 3 个端到端。全部不联网。 |
| 文档 | README / QUICK_START 增加网页版启动方式，Tkinter 标为旧版。设计文档与实施计划在 `docs/superpowers/`。 |

启动：`uv sync --group dev` → `cd frontend && npm i && npm run build` → `uv run ai-trader-web` → `http://127.0.0.1:8000/`。

## 2. 质量评估

### 2.1 做得好的

- **分层清楚**：路由薄、服务是 DataFrame 上的纯函数、错误映射集中在 `app.py`（`ValueError`→422、`ConnectionError`→502）。Web 层从不碰 Tkinter。
- **测试测的是真行为**：假数据源是在 `BinanceDataSource` 类上打补丁，真实的 TA-Lib 指标、形态、`BacktestEngine`、Pydantic 序列化都在跑；`test_analysis_matches_signal_config` 把 API 输出和核心函数直接对账。
- **独立审查发现的问题全部修复并有回归测试**：时间戳被服务器时区偏移（Critical）、start>end 返回 502、缓存对"截止今天"的范围永不刷新、参数越界导致 500、`/symbols` 阻塞事件循环且把断网伪装成空列表、图表每次按键重建、均线周期输入框无法输入、SPA 兜底路由的路径包含检查用了字符串前缀。每一项都是先写出失败测试再修。
- **共享缓存并发安全**：所有消费方都 `copy()` 了缓存的 DataFrame。

### 2.2 保留的小问题（审查定为 Minor，未修）

| 编号 | 问题 | 建议 |
|---|---|---|
| M1 | 所有 `ValueError` 都映射为 422，服务内部的 Pydantic 校验错误或 pandas 错误也会被当成客户端错误 | 定义 `NoDataError(ValueError)`，只映射它 |
| M2 | `/symbols`、`/intervals`、`GET /config/analysis` 没有错误用例 | 补三个测试 |
| M3 | 设计文档提到 EMA 叠加，后端不输出 `ema_*`（Tkinter 也没有） | 要么加，要么从前端 `OVERLAY_PREFIXES` 删掉 |
| M4 | `frontend/README.md` 还是 Vite 模板；根 README 两处仍写 `pip install -r requirements.txt` | 清理 |
| M5 | MACD 柱状图画成了折线 | 用 `HistogramSeries` |
| M7 | 每次 `/analysis/run` 构造两次 `SignalDetector` 加一次 `TechnicalIndicators`，三遍 TA-Lib | ≤1000 根 K 线无感，量大再优化 |
| M9 | SPA 兜底路由不处理 HEAD | 加 `methods=["GET","HEAD"]` |
| M10 | 与 Tkinter 的数值一致性靠代码对读而非录制产物 | 见 2.3 |

### 2.3 未验证项（环境限制）

- **本机无法访问 `api.binance.com`**（curl 返回 000）。所有后端测试用合成 K 线；真实数据下的页面渲染、"数字与 Tkinter 一致"的验收没有跑过。时间戳 Critical 和缓存 Important 两个问题都是真实数据下才会暴露的，这说明**第一次真实数据运行应当作为合并前的条件**。
- uv 管理的 Python 3.12 没有 `_tkinter`，旧版 GUI 的改动只做了 `py_compile` 和代码对读。

## 3. 现有核心模块的问题（改造前就存在，本次按设计不修）

这些是审查和实现过程中读代码发现的，它们同时影响 Tkinter 版和网页版：

1. **DCA 忽略日期范围**：`binance.py` 的 `get_dca_investment_dates` 不用 `start_date`/`end_date` 过滤，而是拉最近 N 根日线（N = 天数差 + 50，上限 1000），再按"几号"筛。只要开始日期不是"最近"，结果就不是用户要的区间。两个 GUI 的数字一样，但一样是错的。
2. **历史数据静默截断**：`get_historical_data` 的 `limit = 天数差`，超过 1000 根被截断，且对闭区间少算一根。
3. **指标参数不影响信号**：界面上的均线周期、MACD/RSI/KDJ/布林参数只用于画图，`SignalDetector` 内部永远用默认周期生成信号（RSI 超买超卖阈值除外）。K 线形态开关同样只影响显示。用户很容易误以为自己在调策略。
4. **回测引擎**：没有资金曲线输出；每次出场重复计算信号强度；手续费和滑点是简单比例；`position_size` 按总资金比例，不考虑已有仓位；夏普用日收益年化 252 而不区分周期。
5. **CLI 的 `backtest` 和 `strategy --run` 是"开发中"占位**；README 承诺的 AI 策略、模拟交易、实盘交易、监控模块**没有对应源码**，只有目录规划。`BaseBroker` 抽象类没有任何实现。
6. **依赖声明与代码脱节**：`sqlalchemy`、`websockets`、`tensorflow`、`torch`、`psycopg2` 在原依赖里但源码没有任何使用（本次已把前两者移除，ML 组保留为可选）。
7. **测试基线极薄**：原来只有 5 个 DCA 单测，其中 1 个实际上在联网。

## 4. 距离接入 Polymarket / Jev 还缺什么

对照调研报告（`docs/research/polymarket-crypto-updown-quant-2026-10-12.md` 第 5 节架构图），现在有的和缺的：

| 层 | 现在有 | 缺 |
|---|---|---|
| 数据 | Binance REST K 线（同步 `requests`） | Binance WebSocket（`@depth@100ms` / `@aggTrade`）；Polymarket Gamma / CLOB / Data API；**PolyBolt `price.crypto.twap` 流**（结算用的 60 秒 TWAP）；本地订单簿维护；带本地接收时间戳的落盘 |
| 定价/信号 | TA 指标、K 线形态、规则信号 | 二元期权定价 `N(d2)` 与**运行中 TWAP 对比开盘 TWAP** 的路径模型；已实现波动率 × 日内季节性；微观结构特征；GBDT/逻辑回归训练与 walk-forward；Jev 文本状态门（新闻/有毒流/规则）作为一列特征或风控门 |
| 执行 | 无（`BaseBroker` 空壳） | Polymarket 统一 SDK（`polymarket-client`）、Session Key 签名、post-only 挂单、幂等下单、150 ms 吃单延迟与订单锁定处理、限流分层响应头 |
| 风控 | 无 | 单笔/日亏损/组合敞口上限、BTC+ETH 合并敞口、VPIN/Z-score/WS 陈旧熔断、费用后 edge 门、¼ Kelly |
| 回测 | 端点结算的规则回测 | 以 `/v2/resolutions` 为标签的 TWAP 结算回放；队列/延迟模型（hftbacktest 或 marketlens SDK）；按 regime 分段；purged CV |
| 实时 | 无 | WebSocket 推送到前端（FastAPI 已留位置）、策略监控面板 |
| 持久化 | 预设 JSON 文件 | 行情/订单/决策审计日志的数据库（原 sqlite 配置无代码） |

网页版为这些留好了位置：`web/api/` 可直接加 `polymarket.py`、`web/services/` 加数据源封装，前端的 React Query + 图表组件可复用。

## 5. 建议的下一步优先级

1. **在能访问币安的网络上跑一次真实数据验收**（README 的三条命令），确认时间轴、图表、回测数字；这是合并前的条件。
2. **修 DCA 日期范围 bug**（第 3 节第 1 条）：改为按 `start_date`/`end_date` 拉取并过滤，补一个用合成数据的单测。
3. **让指标参数真正影响信号，或在界面上明确标注"仅用于显示"**，二选一，避免误导。
4. 清掉 Minor 列表里的 M1、M4、M5，成本都很低。
5. 之后再按第 4 节从数据层开始接 Polymarket：先 Gamma + PolyBolt TWAP 流 + 本地落盘，只读，不接执行；评估模型时先过"融合后 Brier 优于 Polymarket 中间价"的门槛（见调研报告）。

## 6. 执行记录

实施按 `docs/superpowers/plans/2026-10-12-web-version.md` 的 14 个任务逐一 TDD 完成，共 18 条有记录的裁定（环境限制、版本漂移、审查中"不在范围"的项），全部在本文第 2.3 和第 3 节有对应说明。独立审查结论为"With fixes"，修复后三套测试均通过：pytest 56、vitest 10、Playwright 3。
