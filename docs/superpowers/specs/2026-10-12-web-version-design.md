# ai_trader 网页版改造设计

日期：2026-10-12
状态：已与项目负责人确认

## 1. 目标与背景

把现有的 Tkinter 桌面 GUI 替换为浏览器界面，作为后续量化系统（Polymarket / Jev 接入、实时监控、策略面板）的基础。本次只搬运现有的两个可用功能：定投收益计算（DCA）和技术分析（K 线加载、指标、K 线形态、信号、回测、参数预设）。

成功标准：启动 `ai-trader-web` 后，在浏览器中完成定投计算、加载 K 线、看到指标与信号、运行回测，且数字与 Tkinter 版一致。

用户已确认的决定：
- 用途：后续量化系统的基础（前后端分离）。
- 路线：FastAPI 后端 + React/Vite/TypeScript 前端 + lightweight-charts 图表。
- 评估：改造完成后出一份项目质量与缺口评估（单独文档，不在本设计范围内实现）。

## 2. 架构

```
浏览器 (React + lightweight-charts)
   │  REST /api/*          （后续可加 WebSocket）
   ▼
FastAPI  src/ai_trader/web/
   ├── app.py              应用工厂、CORS、生产时挂载 frontend/dist
   ├── schemas.py          Pydantic 请求/响应模型
   ├── api/
   │   ├── market.py       symbols / intervals / klines
   │   ├── dca.py          calculate
   │   ├── analysis.py     run
   │   ├── backtest.py     run
   │   └── config.py       analysis 预设 GET/PUT
   └── services/
       ├── market_data.py  BinanceDataSource 封装 + K 线 LRU 缓存 + DataFrame→JSON
       ├── analysis.py     指标/形态/信号 编排
       └── backtest.py     BacktestEngine 编排
   │  调用
   ▼
现有 core/analysis, core/data, strategies（接口不变）
```

- 运行方式：开发时后端 `uv run ai-trader-web`（uvicorn，端口 8000），前端 `npm run dev`（Vite，端口 5173，`/api` 代理到 8000）。生产时 `npm run build` 输出 `frontend/dist`，由 FastAPI 以静态文件挂载，单进程运行。
- 现有 Tkinter GUI、matplotlib 出图、CLI 保留不删；README 把 Tkinter 标为旧版入口。
- Python 依赖新增：fastapi、uvicorn[standard]、httpx（测试）。用 uv 管理；pyproject 新增脚本 `ai-trader-web = "ai_trader.web.app:main"`。不改动现有 tensorflow/torch 声明。
- 前端依赖：react、react-dom、react-router-dom、@tanstack/react-query、lightweight-charts、tailwindcss、vite、typescript、vitest、@playwright/test。

## 3. 后端 API

统一前缀 `/api`。错误响应统一为 `{"detail": "..."}`：请求参数错误 422（Pydantic），币安不可达或返回异常 502，内部错误 500。

| 方法与路径 | 入参 | 返回 |
|---|---|---|
| `GET /api/market/symbols?mainstream_only=true` | query | `{"symbols": ["BTCUSDT", ...]}` |
| `GET /api/market/intervals` | 无 | `{"intervals": ["1m", ..., "1d"]}` |
| `GET /api/market/klines?symbol&interval&start&end` | query，start/end 为 `YYYY-MM-DD` | `{"bars": [{"time": 1700000000, "open": ..., "high": ..., "low": ..., "close": ..., "volume": ...}]}`，time 为 Unix 秒 |
| `POST /api/dca/calculate` | `{symbol, amount, day, start_date, end_date?}` | 现有 `DCAStrategy.execute_dca()` 的字典原样返回，`records[].date` 序列化为 `YYYY-MM-DD` |
| `POST /api/analysis/run` | `{symbol, interval, start, end, params: SignalConfig}` | `{"indicators": {"sma_short": [...], "sma_long": [...], "ema": [...], "bb_upper": [...], "bb_middle": [...], "bb_lower": [...], "rsi": [...], "macd": [...], "macd_signal": [...], "macd_hist": [...], "kdj_k": [...], "kdj_d": [...], "kdj_j": [...]}, "patterns": {"hammer": [time...], ...}, "entry_signals": [time...], "exit_signals": [time...], "effectiveness": {...现有 analyze_signal_effectiveness 的字典}}`。指标数组与 bars 等长，NaN 序列化为 null |
| `POST /api/backtest/run` | analysis 的入参 + `{initial_capital, position_size, commission_rate, slippage_rate}` | `BacktestResult` 的 JSON：标量字段 + `trades[]`，时间序列化为 Unix 秒 |
| `GET /api/config/analysis` | 无 | 当前预设（`SignalConfig` + 回测参数） |
| `PUT /api/config/analysis` | 同上结构 | 保存到 `data/analysis_config.json`，返回保存后的内容 |

- K 线缓存：`services/market_data.py` 内 `functools.lru_cache`（maxsize 32），键为 (symbol, interval, start, end)。analysis 和 backtest 复用同一缓存，不重复拉币安。
- 长任务：路由内用 `fastapi.concurrency.run_in_threadpool` 调用同步服务函数。不引入任务队列。

### 3.1 必要重构：信号配置从 Tkinter 页面抽出

现状：`gui/pages/technical_analysis_page.py` 的 `create_custom_signal_detector()` 在方法内定义 `CustomSignalDetector` 子类，直接读取 tk 变量（RSI 阈值、均线周期、布林参数、形态开关、信号权重等）。Web 无法复用。

改动：
- 在 `core/analysis/signals.py` 新增 `@dataclass SignalConfig`，字段覆盖 Tkinter 页面所有可调参数，默认值与页面默认值一致。
- `SignalDetector` 新增 `get_custom_entry_signals(config: SignalConfig) -> pd.Series` 与 `get_custom_exit_signals(config: SignalConfig) -> pd.Series`，逻辑从 Tkinter 内部类原样迁移。
- Tkinter 页面改为构造 `SignalConfig` 后调用上述方法，行为不变。
- 为这两个方法补单测（用录制的样本数据，断言与迁移前结果一致）。

## 4. 前端

- 路由：`/dca`、`/analysis`，默认跳转 `/analysis`。顶栏导航项与 Tkinter 版一致：定投计算、技术分析可点；策略管理、回测、监控、设置显示为禁用项。
- 定投页：表单（交易对下拉、仅主流币复选、金额、每月日期、开始/结束日期）+ 汇总卡片 + 定投明细表。
- 技术分析页：
  - 左侧参数面板，五个折叠组：数据（交易对、周期、日期范围、加载按钮）、指标（周期参数）、形态（开关）、信号（阈值与权重）、回测（资金、仓位、手续费、滑点）。
  - 右侧上方图表区：主图蜡烛 + 成交量，SMA/EMA/布林叠加；RSI、MACD、KDJ 各一个子图；入场/出场信号用 marker。
  - 右侧下方三个标签页：分析结果（信号数量与有效性统计）、信号详情（入场/出场时间与价格表）、回测结果（指标卡片 + 交易记录表）。
  - 预设：保存/加载按钮调用 config API。
- 数据层：React Query 管理请求与缓存；组件内状态用 useState；不引入全局 store。
- 样式：Tailwind，不引入组件库。

## 5. 测试与验收

- 后端：pytest + `fastapi.testclient.TestClient`。`tests/fixtures/btcusdt_1d_sample.json` 录制一段 BTCUSDT 日线（约 400 根），fixture 把 `BinanceDataSource.get_historical_data` / `get_available_symbols` / `get_current_price` / `get_dca_investment_dates` 替换为读样本，测试不联网。每个路由至少一个成功用例和一个 422/502 用例。
- 信号重构：`tests/unit/test_signal_config.py` 断言默认 `SignalConfig` 下 `get_custom_entry_signals` 的结果与迁移前 Tkinter 内部类输出一致（迁移前先录一份期望输出）。
- 前端：vitest 对 DCA 表单和参数面板做冒烟；Playwright 一个端到端用例（mock `/api`）：加载数据 → 分析 → 回测，断言三个标签页出现内容。
- 验收：按第 1 节成功标准手动走一遍。

## 6. 明确不做

认证、Docker、任务队列、WebSocket 实时行情、Polymarket / Jev 接入、现有回测引擎与信号逻辑的缺陷修复、删除 Tkinter 代码。路由目录结构为后续模块预留位置。

## 7. 风险

- 币安 API 在部分网络环境不可达：测试已 mock；运行时返回 502 并在前端提示。
- Python 3.9 环境：fastapi/pydantic v2 支持 3.8+，无冲突。
- 现有 `analyze_signal_effectiveness` 返回结构未在本设计中逐字段约定，实现时以其实际返回为准透传。
