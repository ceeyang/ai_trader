# ai_trader 网页版 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把现有 Tkinter 桌面 GUI 的两个可用功能（定投计算、技术分析）搬到浏览器，后端 FastAPI、前端 React，数字与 Tkinter 版一致。

**Architecture:** FastAPI 在 `src/ai_trader/web/` 下把现有 `core/`、`strategies/` 包成 REST API（services 薄层负责 DataFrame→JSON 和 K 线缓存）。前端 `frontend/` 用 Vite + React + TypeScript + Tailwind，K 线用 lightweight-charts 在浏览器渲染。信号组合逻辑从 Tkinter 页面抽到 `core/analysis/signals.py` 的 `SignalConfig`，三端共用。

**Tech Stack:** Python 3.12（uv 管理）、FastAPI、Pydantic v2、uvicorn、httpx（测试）、pytest；Node 26、Vite、React 18、TypeScript、Tailwind、@tanstack/react-query、react-router-dom、lightweight-charts、vitest、@playwright/test。

**Spec:** `docs/superpowers/specs/2026-10-12-web-version-design.md`

## Global Constraints

- Python `requires-python = ">=3.11"`；本机用 uv 装 3.12。`ta-lib` 0.8.x 的 wheel 自带 C 库，不需要 brew。
- 现有 `core/`、`strategies/` 模块的公开接口不改；唯一新增是 `SignalConfig` 与两个方法（Task 3）。
- Tkinter GUI、matplotlib、CLI 保留不删。
- API 前缀 `/api`；错误响应 `{"detail": "..."}`；参数错误 422，币安不可达 502。
- 时间一律序列化为 Unix 秒整数；NaN 序列化为 `null`。
- 测试不联网：所有后端测试通过 `fake_data_source` fixture 替换币安调用。
- 前端不引入组件库、不引入全局 store。
- 每个任务结束提交一次，提交信息末尾加 `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`。
- 与 spec 的两处偏差（已决定）：(1) 测试样本用确定性合成 OHLCV（种子固定）而非录制的币安数据，避免录制步骤依赖网络；(2) 指标键名沿用 Tkinter 的 `macd_dif/macd_dea/macd_hist`、`sma_{period}`，而不是 spec 表格里的示意名。

## Review Focus

1. 日期范围内币安返回空 K 线（例如新币或 start > end）：analysis/backtest 应返回 422 "no data"，不是 500。测试在 Task 5。
2. `min_conditions` 大于启用的条件数：Tkinter 逻辑返回全 False 信号；Web 必须保持一致而不是报错。测试在 Task 3。
3. 指标周期大于数据长度（如 200 日均线、只有 100 根 K 线）：Tkinter 跳过该均线；Web 同样跳过并且不出 500。测试在 Task 7。
4. 回测无交易（信号全 False）：`BacktestResult` 的 `win_rate`、`sharpe_ratio` 可能除零得 NaN；响应必须是合法 JSON（NaN→null）。测试在 Task 8。
5. 前端在后端返回 502 时要显示错误提示而不是空白；端到端用例覆盖。测试在 Task 13。

---

### Task 1: 项目环境与依赖整理

**Files:**
- Modify: `pyproject.toml`
- Modify: `.gitignore`
- Modify: `requirements.txt`（改为注释"请用 uv sync"，保留以兼容旧文档）

**Interfaces:**
- Produces: 可用的 `uv sync` 环境；`uv run pytest` 跑通现有 `tests/unit/test_dca_strategy.py`。

- [ ] **Step 1: 改 `pyproject.toml`**

  - `requires-python = ">=3.11"`；classifiers 只保留 3.11/3.12。
  - `dependencies` 只保留运行时：`requests`, `pandas`, `numpy`, `pyyaml`, `ta-lib>=0.6`, `matplotlib>=3.5`, `fastapi>=0.115`, `uvicorn[standard]>=0.30`, `pydantic>=2.7`。
  - 删除 `sqlalchemy`、`websockets`（无代码使用）和所有 dev 工具。
  - 删除 `gui`、`database` 两个 optional 组（`tkinter`、`sqlite3` 不是 PyPI 包，会让 uv 解析失败）；保留 `ml`。
  - 新增 `[dependency-groups] dev = ["pytest>=8", "pytest-cov>=5", "httpx>=0.27", "black", "flake8", "mypy"]`。
  - `[project.scripts]` 新增 `ai-trader-web = "ai_trader.web.app:main"`。
  - `[tool.pytest.ini_options].addopts` 删除三个 `--cov*` 项（覆盖率按需手动加），保留 `--strict-markers --strict-config`。
  - `[tool.black].target-version = ['py311']`，`[tool.mypy].python_version = "3.11"`。

- [ ] **Step 2: 改 `.gitignore`**：追加 `.venv/`、`uv.lock` 不忽略（要提交）、`data/`、`frontend/node_modules/`、`frontend/dist/`、`frontend/test-results/`、`frontend/playwright-report/`。

- [ ] **Step 3: 同步环境**

Run: `uv python pin 3.12 && uv sync --group dev`
Expected: 结束无 error；`.python-version` 文件生成。

- [ ] **Step 4: 验证现有测试**

Run: `uv run pytest tests/unit/test_dca_strategy.py -q`
Expected: 全部 PASS（若因 `from src.ai_trader` 导入失败，在 `pyproject.toml` 的 `[tool.pytest.ini_options]` 加 `pythonpath = ["."]`）。

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .gitignore .python-version uv.lock requirements.txt
git commit -m "chore: switch to uv, add web deps, drop invalid extras"
```

---

### Task 2: 测试夹具：合成 K 线与假数据源

**Files:**
- Create: `tests/conftest.py`
- Test: `tests/unit/test_conftest_fixture.py`

**Interfaces:**
- Produces:
  - `make_sample_ohlcv(n: int = 400, seed: int = 42, start: str = "2024-01-01", freq: str = "D") -> pd.DataFrame`：列 `open, high, low, close, volume`，`DatetimeIndex`，收盘价为种子随机游走（起点 40000，日波动 2%），`high >= max(open, close)`，`low <= min(open, close)`。
  - pytest fixture `sample_ohlcv` → 上述 DataFrame。
  - pytest fixture `fake_data_source(monkeypatch)`：用 `monkeypatch.setattr` 替换 `ai_trader.core.data.providers.binance.BinanceDataSource` 的 `connect`（返回 True）、`disconnect`、`get_historical_data`（返回 `sample_ohlcv` 按 start/end 切片）、`get_available_symbols`（返回 `["BTCUSDT", "ETHUSDT"]`）、`get_current_price`（返回最后一根 close）、`get_dca_investment_dates`（从 `sample_ohlcv` 里挑 `day == invest_day` 的行，返回 `[{date, datetime, close}]`）。
  - pytest fixture `broken_data_source(monkeypatch)`：`get_historical_data` / `get_dca_investment_dates` / `get_available_symbols` 抛 `ConnectionError("binance unreachable")`。

- [ ] **Step 1: 写失败测试**

```python
def test_sample_ohlcv_shape(sample_ohlcv):
    assert len(sample_ohlcv) == 400
    assert list(sample_ohlcv.columns) == ["open", "high", "low", "close", "volume"]
    assert (sample_ohlcv["high"] >= sample_ohlcv[["open", "close"]].max(axis=1)).all()
    assert (sample_ohlcv["low"] <= sample_ohlcv[["open", "close"]].min(axis=1)).all()

def test_sample_is_deterministic():
    from tests.conftest import make_sample_ohlcv
    assert make_sample_ohlcv().equals(make_sample_ohlcv())

def test_fake_data_source_slices(fake_data_source):
    from datetime import datetime
    from ai_trader.core.data.providers.binance import BinanceDataSource
    ds = BinanceDataSource(); ds.connect()
    df = ds.get_historical_data("BTCUSDT", "1d", datetime(2024, 3, 1), datetime(2024, 3, 31))
    assert len(df) == 31
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/unit/test_conftest_fixture.py -q`
Expected: FAIL（fixture 不存在）

- [ ] **Step 3: 实现 `tests/conftest.py`**（函数与 fixture 按 Interfaces）

- [ ] **Step 4: 运行通过**

Run: `uv run pytest tests/unit/test_conftest_fixture.py -q`
Expected: 3 passed

- [ ] **Step 5: Commit** `git add tests/ && git commit -m "test: synthetic OHLCV fixture and fake Binance data source"`

---

### Task 3: 把自定义信号逻辑抽成 `SignalConfig`

**Files:**
- Modify: `src/ai_trader/core/analysis/signals.py`
- Modify: `src/ai_trader/gui/pages/technical_analysis_page.py:677-807`（`create_custom_signal_detector`）
- Test: `tests/unit/test_signal_config.py`

**Interfaces:**
- Produces（在 `signals.py`）：
  ```python
  @dataclass
  class SignalConfig:
      rsi_oversold: int = 30
      rsi_overbought: int = 70
      trend_required: bool = True
      macd_required: bool = True
      rsi_required: bool = True
      kdj_required: bool = True
      bb_required: bool = True
      pattern_required: bool = True
      volume_required: bool = True
      combination: str = "all"      # "all" | "min"
      min_conditions: int = 2
  ```
  `SignalDetector.get_custom_entry_signals(self, config: SignalConfig) -> pd.Series`
  `SignalDetector.get_custom_exit_signals(self, config: SignalConfig) -> pd.Series`
  逻辑与 Tkinter 内部类逐行一致：入场按 `combination` 做 AND 或 "满足数 ≥ min_conditions"；若 `len(conditions) < min_conditions` 返回全 False；出场为启用条件的 OR（出场不含 volume）。

- [ ] **Step 1: 写失败测试**

```python
import pandas as pd
from ai_trader.core.analysis.signals import SignalDetector, SignalConfig
from ai_trader.core.analysis.patterns import CandlestickPatterns

def test_entry_all_mode_equals_and_of_components(sample_ohlcv):
    d = SignalDetector(sample_ohlcv)
    cfg = SignalConfig()
    trend = d.get_trend_direction(); macd, _ = d.get_macd_signals()
    rsi, _ = d.get_rsi_signals(30, 70); kdj, _ = d.get_kdj_signals()
    bb, _ = d.get_bollinger_signals(); vol = d.get_volume_confirmation()
    pat = CandlestickPatterns(sample_ohlcv).get_bullish_patterns()
    expected = (trend == 1) & macd & rsi & kdj & bb & pat & vol
    pd.testing.assert_series_equal(d.get_custom_entry_signals(cfg), expected, check_names=False)

def test_entry_min_mode_counts_conditions(sample_ohlcv):
    d = SignalDetector(sample_ohlcv)
    cfg = SignalConfig(combination="min", min_conditions=2, pattern_required=False, volume_required=False)
    trend = d.get_trend_direction(); macd, _ = d.get_macd_signals()
    rsi, _ = d.get_rsi_signals(30, 70); kdj, _ = d.get_kdj_signals(); bb, _ = d.get_bollinger_signals()
    count = (trend == 1).astype(int) + macd.astype(int) + rsi.astype(int) + kdj.astype(int) + bb.astype(int)
    pd.testing.assert_series_equal(d.get_custom_entry_signals(cfg), count >= 2, check_names=False)

def test_min_conditions_above_enabled_returns_all_false(sample_ohlcv):
    d = SignalDetector(sample_ohlcv)
    cfg = SignalConfig(combination="min", min_conditions=3, trend_required=True,
                       macd_required=False, rsi_required=False, kdj_required=False,
                       bb_required=False, pattern_required=False, volume_required=False)
    assert not d.get_custom_entry_signals(cfg).any()

def test_exit_is_or_of_enabled(sample_ohlcv):
    d = SignalDetector(sample_ohlcv)
    cfg = SignalConfig(trend_required=False, kdj_required=False, bb_required=False, pattern_required=False)
    _, macd = d.get_macd_signals(); _, rsi = d.get_rsi_signals(30, 70)
    pd.testing.assert_series_equal(d.get_custom_exit_signals(cfg), macd | rsi, check_names=False)

def test_no_conditions_returns_all_false(sample_ohlcv):
    d = SignalDetector(sample_ohlcv)
    cfg = SignalConfig(**{k: False for k in ["trend_required","macd_required","rsi_required","kdj_required","bb_required","pattern_required","volume_required"]})
    assert not d.get_custom_entry_signals(cfg).any() and not d.get_custom_exit_signals(cfg).any()
```

- [ ] **Step 2: 运行确认失败**：`uv run pytest tests/unit/test_signal_config.py -q` → ImportError

- [ ] **Step 3: 实现 `SignalConfig` 和两个方法**（把 Tkinter 内部类的两个函数体搬过来，`self.parent_detector.X.get()` 换成 `config.X`）

- [ ] **Step 4: 运行通过**：5 passed

- [ ] **Step 5: 改 Tkinter 页面**：`create_custom_signal_detector` 改为从 tk 变量构造 `SignalConfig`，返回的检测器把 `get_comprehensive_entry_signals` 绑定为 `lambda: detector.get_custom_entry_signals(cfg)`（出场同理）；删除内部类。

- [ ] **Step 6: 冒烟**：`uv run python -c "import ai_trader.gui.pages.technical_analysis_page"` 无报错；全量 `uv run pytest -q` 通过。

- [ ] **Step 7: Commit** `git commit -am "refactor: extract SignalConfig from Tkinter page into SignalDetector"`

---

### Task 4: FastAPI 骨架与健康检查

**Files:**
- Create: `src/ai_trader/web/__init__.py`、`src/ai_trader/web/app.py`、`src/ai_trader/web/api/__init__.py`
- Test: `tests/web/__init__.py`、`tests/web/conftest.py`、`tests/web/test_app.py`

**Interfaces:**
- Produces:
  - `create_app() -> fastapi.FastAPI`：注册 `/api/health`，CORS 允许 `http://localhost:5173`；若 `Path(__file__).parents[3] / "frontend" / "dist"` 存在，则 `app.mount("/", StaticFiles(directory=..., html=True))`（必须在所有 `/api` 路由之后挂载）。
  - `main() -> None`：`uvicorn.run("ai_trader.web.app:create_app", factory=True, host="127.0.0.1", port=8000, reload=False)`。
  - `tests/web/conftest.py` fixture `client` → `fastapi.testclient.TestClient(create_app())`。

- [ ] **Step 1: 写失败测试**

```python
def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}
```

- [ ] **Step 2: 运行确认失败**：`uv run pytest tests/web/test_app.py -q` → ImportError
- [ ] **Step 3: 实现 `app.py`**
- [ ] **Step 4: 运行通过**
- [ ] **Step 5: 手动验证入口**：`uv run ai-trader-web &` 后 `curl -s localhost:8000/api/health` 返回 `{"status":"ok"}`，然后结束进程。
- [ ] **Step 6: Commit** `git commit -m "feat(web): FastAPI app skeleton with health endpoint"`

---

### Task 5: 行情服务与 market API

**Files:**
- Create: `src/ai_trader/web/schemas.py`、`src/ai_trader/web/services/__init__.py`、`src/ai_trader/web/services/market_data.py`、`src/ai_trader/web/api/market.py`
- Modify: `src/ai_trader/web/app.py`（include_router）
- Test: `tests/web/test_market.py`、`tests/unit/test_market_service.py`

**Interfaces:**
- Produces（`schemas.py`，Pydantic v2，全部 snake_case）：
  `Bar(time: int, open: float, high: float, low: float, close: float, volume: float)`、`KlinesResponse(bars: list[Bar])`、`SymbolsResponse(symbols: list[str])`、`IntervalsResponse(intervals: list[str])`。
- Produces（`services/market_data.py`）：
  - `get_data_source() -> BinanceDataSource`：模块级单例，首次调用 `connect()`。
  - `fetch_klines(symbol: str, interval: str, start: str, end: str) -> pd.DataFrame`：`@functools.lru_cache(maxsize=32)`；参数为 `YYYY-MM-DD` 字符串；内部 `datetime.strptime`；对 `requests.exceptions.RequestException` 包装为 `ConnectionError`；返回空 DataFrame 时抛 `ValueError("no data for range")`。
  - `df_to_bars(df: pd.DataFrame) -> list[Bar]`：`time = int(ts.timestamp())`。
  - `nan_to_none(series: pd.Series) -> list[float | None]`。
- Produces（`api/market.py` router，prefix `/api/market`）：`GET /symbols?mainstream_only: bool = true`、`GET /intervals`、`GET /klines?symbol&interval&start&end`。
- 错误映射（放在 `app.py` 的 exception handlers，后续任务共用）：`ConnectionError` → 502 `{"detail": str(e)}`；`ValueError` → 422 `{"detail": str(e)}`。

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/test_market_service.py
def test_fetch_klines_is_cached(fake_data_source, monkeypatch):
    from ai_trader.web.services import market_data as m
    m.fetch_klines.cache_clear()
    calls = []
    orig = m.get_data_source().get_historical_data
    monkeypatch.setattr(m.get_data_source(), "get_historical_data", lambda *a, **k: (calls.append(1), orig(*a, **k))[1])
    m.fetch_klines("BTCUSDT", "1d", "2024-02-01", "2024-02-29")
    m.fetch_klines("BTCUSDT", "1d", "2024-02-01", "2024-02-29")
    assert len(calls) == 1

def test_df_to_bars_time_is_unix_seconds(sample_ohlcv):
    from ai_trader.web.services.market_data import df_to_bars
    bars = df_to_bars(sample_ohlcv.head(1))
    assert bars[0].time == int(sample_ohlcv.index[0].timestamp())

# tests/web/test_market.py
def test_symbols(client, fake_data_source):
    assert client.get("/api/market/symbols").json() == {"symbols": ["BTCUSDT", "ETHUSDT"]}

def test_klines_ok(client, fake_data_source):
    r = client.get("/api/market/klines", params={"symbol": "BTCUSDT", "interval": "1d", "start": "2024-03-01", "end": "2024-03-31"})
    assert r.status_code == 200 and len(r.json()["bars"]) == 31
    assert set(r.json()["bars"][0]) == {"time", "open", "high", "low", "close", "volume"}

def test_klines_bad_date_422(client, fake_data_source):
    assert client.get("/api/market/klines", params={"symbol": "BTCUSDT", "interval": "1d", "start": "bad", "end": "2024-03-31"}).status_code == 422

def test_klines_empty_range_422(client, fake_data_source):
    r = client.get("/api/market/klines", params={"symbol": "BTCUSDT", "interval": "1d", "start": "2030-01-01", "end": "2030-01-02"})
    assert r.status_code == 422 and "no data" in r.json()["detail"]

def test_klines_binance_down_502(client, broken_data_source):
    assert client.get("/api/market/klines", params={"symbol": "BTCUSDT", "interval": "1d", "start": "2024-03-01", "end": "2024-03-31"}).status_code == 502
```

注意：`fetch_klines` 是 lru_cache，测试之间要在 `tests/web/conftest.py` 的 `client` fixture 里 `fetch_klines.cache_clear()`，并且 `get_data_source()` 的单例要在 fixture 里重置（提供 `market_data.reset_data_source()` 供测试用）。

- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现 schemas、service、router、exception handlers**
- [ ] **Step 4: 运行通过**：`uv run pytest tests/unit/test_market_service.py tests/web/test_market.py -q`
- [ ] **Step 5: Commit** `git commit -m "feat(web): market data service and /api/market endpoints"`

---

### Task 6: DCA API

**Files:**
- Modify: `src/ai_trader/web/schemas.py`
- Create: `src/ai_trader/web/api/dca.py`
- Modify: `src/ai_trader/web/app.py`
- Test: `tests/web/test_dca.py`

**Interfaces:**
- Produces：`DCARequest(symbol: str, amount: float = Field(gt=0), day: int = Field(ge=1, le=31), start_date: date, end_date: date | None = None)`；`DCARecord(date: str, price: float, amount: float, coins: float)`；`DCAResponse(symbol, total_invested, total_coins, current_price, total_value, profit, profit_rate, average_cost, investment_count: int, records: list[DCARecord])`。
- `POST /api/dca/calculate`：构造 `DCAStrategy(symbol, invest_amount, invest_day, start_date, end_date or datetime.now())`，`run_in_threadpool(strategy.execute_dca)`，结果直接构造 `DCAResponse`。

- [ ] **Step 1: 写失败测试**

```python
def test_dca_calculate(client, fake_data_source):
    r = client.post("/api/dca/calculate", json={"symbol": "BTCUSDT", "amount": 200, "day": 10, "start_date": "2024-01-01", "end_date": "2024-12-31"})
    body = r.json()
    assert r.status_code == 200
    assert body["investment_count"] == len(body["records"]) > 0
    assert abs(body["total_invested"] - 200 * body["investment_count"]) < 1e-6

def test_dca_validation_422(client, fake_data_source):
    assert client.post("/api/dca/calculate", json={"symbol": "BTCUSDT", "amount": -1, "day": 10, "start_date": "2024-01-01"}).status_code == 422

def test_dca_binance_down_502(client, broken_data_source):
    assert client.post("/api/dca/calculate", json={"symbol": "BTCUSDT", "amount": 200, "day": 10, "start_date": "2024-01-01"}).status_code == 502
```

- [ ] **Step 2: 运行确认失败** → 404
- [ ] **Step 3: 实现**
- [ ] **Step 4: 运行通过**
- [ ] **Step 5: Commit** `git commit -m "feat(web): /api/dca/calculate"`

---

### Task 7: 分析服务与 analysis API

**Files:**
- Modify: `src/ai_trader/web/schemas.py`
- Create: `src/ai_trader/web/services/analysis.py`、`src/ai_trader/web/api/analysis.py`
- Modify: `src/ai_trader/web/app.py`
- Test: `tests/unit/test_analysis_service.py`、`tests/web/test_analysis.py`

**Interfaces:**
- Produces（schemas）：
  - `IndicatorParams(sma_periods: list[int] = [5,10,20,50,200], macd_fast: int = 12, macd_slow: int = 26, macd_signal: int = 9, rsi_period: int = 14, kdj_k: int = 9, kdj_d: int = 3, kdj_j: int = 3, bb_period: int = 20, bb_std: float = 2.0)`
  - `SignalParams`：字段与 `SignalConfig` 一一对应，`combination: Literal["all","min"]`；方法 `to_config() -> SignalConfig`。
  - `DataRange(symbol: str, interval: str, start: date, end: date)`
  - `AnalysisRequest(data: DataRange, indicators: IndicatorParams = IndicatorParams(), signals: SignalParams = SignalParams())`
  - `EffectivenessStat(frequency: float, avg_price_change_1d: float, positive_rate: float)`
  - `AnalysisResponse(indicators: dict[str, list[float | None]], patterns: dict[str, list[int]], entry_signals: list[int], exit_signals: list[int], effectiveness: dict[str, EffectivenessStat])`
- Produces（`services/analysis.py`）：
  - `compute_indicators(df, params: IndicatorParams) -> dict[str, list[float | None]]`：键 `sma_{p}`（`p <= len(df)` 才算）、`macd_dif`、`macd_dea`、`macd_hist`、`rsi`、`kdj_k`、`kdj_d`、`kdj_j`、`bb_upper`、`bb_middle`、`bb_lower`；用 `TechnicalIndicators`。
  - `compute_patterns(df) -> dict[str, list[int]]`：`CandlestickPatterns(df).get_all_patterns()` 每个布尔序列转为 True 处的 Unix 秒列表。
  - `compute_signals(df, config: SignalConfig) -> tuple[list[int], list[int]]`。
  - `compute_effectiveness(df) -> dict[str, EffectivenessStat]`：`BacktestEngine(df).analyze_signal_effectiveness()` 透传。
  - `run_analysis(req: AnalysisRequest) -> AnalysisResponse`：`fetch_klines` → 以上四步。
- `POST /api/analysis/run`。

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/test_analysis_service.py
def test_sma_longer_than_data_is_skipped(sample_ohlcv):
    from ai_trader.web.services.analysis import compute_indicators
    from ai_trader.web.schemas import IndicatorParams
    out = compute_indicators(sample_ohlcv.head(100), IndicatorParams(sma_periods=[20, 200]))
    assert "sma_20" in out and "sma_200" not in out
    assert len(out["sma_20"]) == 100 and out["sma_20"][0] is None

def test_patterns_are_unix_seconds(sample_ohlcv):
    from ai_trader.web.services.analysis import compute_patterns
    out = compute_patterns(sample_ohlcv)
    assert "hammer" in out and all(isinstance(t, int) for t in out["hammer"])

# tests/web/test_analysis.py
BODY = {"data": {"symbol": "BTCUSDT", "interval": "1d", "start": "2024-01-01", "end": "2025-02-03"}}

def test_analysis_run_shape(client, fake_data_source):
    r = client.post("/api/analysis/run", json=BODY)
    b = r.json()
    assert r.status_code == 200
    assert set(b) == {"indicators", "patterns", "entry_signals", "exit_signals", "effectiveness"}
    assert len(b["indicators"]["rsi"]) == 400
    assert all(isinstance(t, int) for t in b["entry_signals"])

def test_analysis_matches_signal_config(client, fake_data_source, sample_ohlcv):
    from ai_trader.core.analysis.signals import SignalDetector, SignalConfig
    r = client.post("/api/analysis/run", json={**BODY, "signals": {"combination": "min", "min_conditions": 2}})
    expected = SignalDetector(sample_ohlcv).get_custom_entry_signals(SignalConfig(combination="min", min_conditions=2))
    assert r.json()["entry_signals"] == [int(t.timestamp()) for t in sample_ohlcv.index[expected]]

def test_analysis_empty_range_422(client, fake_data_source):
    r = client.post("/api/analysis/run", json={"data": {"symbol": "BTCUSDT", "interval": "1d", "start": "2030-01-01", "end": "2030-01-02"}})
    assert r.status_code == 422
```

- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现**
- [ ] **Step 4: 运行通过**
- [ ] **Step 5: Commit** `git commit -m "feat(web): analysis service and /api/analysis/run"`

---

### Task 8: 回测 API

**Files:**
- Modify: `src/ai_trader/web/schemas.py`
- Create: `src/ai_trader/web/services/backtest.py`、`src/ai_trader/web/api/backtest.py`
- Modify: `src/ai_trader/web/app.py`
- Test: `tests/web/test_backtest.py`

**Interfaces:**
- Produces（schemas）：`BacktestParams(initial_capital: float = 100000, position_size: float = 0.1, commission_rate: float = 0.001, slippage_rate: float = 0.0005)`；`BacktestRequest(AnalysisRequest 的三个字段 + backtest: BacktestParams = BacktestParams())`；`TradeOut(entry_time: int, exit_time: int, entry_price, exit_price, quantity, pnl, pnl_percent, duration: int, signal_strength: float)`；`BacktestResponse(total_trades: int, winning_trades: int, losing_trades: int, win_rate: float | None, total_pnl: float, total_return: float, max_drawdown: float, sharpe_ratio: float | None, avg_trade_duration: float | None, trades: list[TradeOut])`。
- Produces（service）：`run_backtest(req: BacktestRequest) -> BacktestResponse`：`fetch_klines` → `BacktestEngine(df, initial_capital)`，设置 `commission_rate`/`slippage_rate` 属性 → `SignalDetector(df).get_custom_entry/exit_signals(config)` → `run_backtest(entry, exit, position_size)` → 序列化；NaN 标量转 `None`。
- `POST /api/backtest/run`。

- [ ] **Step 1: 写失败测试**

```python
BODY = {"data": {"symbol": "BTCUSDT", "interval": "1d", "start": "2024-01-01", "end": "2025-02-03"}}

def test_backtest_shape(client, fake_data_source):
    r = client.post("/api/backtest/run", json=BODY)
    b = r.json()
    assert r.status_code == 200
    assert b["total_trades"] == b["winning_trades"] + b["losing_trades"] == len(b["trades"])

def test_backtest_no_trades_is_valid_json(client, fake_data_source):
    flags = {k: False for k in ["trend_required","macd_required","rsi_required","kdj_required","bb_required","pattern_required","volume_required"]}
    r = client.post("/api/backtest/run", json={**BODY, "signals": flags})
    assert r.status_code == 200 and r.json()["total_trades"] == 0

def test_backtest_params_422(client, fake_data_source):
    assert client.post("/api/backtest/run", json={**BODY, "backtest": {"position_size": "x"}}).status_code == 422
```

- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现**
- [ ] **Step 4: 运行通过**
- [ ] **Step 5: Commit** `git commit -m "feat(web): /api/backtest/run"`

---

### Task 9: 分析参数预设 API

**Files:**
- Modify: `src/ai_trader/web/schemas.py`
- Create: `src/ai_trader/web/services/presets.py`、`src/ai_trader/web/api/config.py`
- Modify: `src/ai_trader/web/app.py`
- Test: `tests/web/test_config.py`

**Interfaces:**
- `AnalysisPreset(indicators: IndicatorParams = ..., signals: SignalParams = ..., backtest: BacktestParams = ...)`。
- `services/presets.py`：`preset_path() -> Path`：`Path(os.environ.get("AI_TRADER_DATA_DIR", "data")) / "analysis_config.json"`；`load_preset() -> AnalysisPreset`（文件不存在返回默认）；`save_preset(p: AnalysisPreset) -> None`（`mkdir(parents=True)`，`model_dump_json(indent=2)`）。
- `GET /api/config/analysis`、`PUT /api/config/analysis`（body 为 `AnalysisPreset`，返回保存后的内容）。

- [ ] **Step 1: 写失败测试**（`monkeypatch.setenv("AI_TRADER_DATA_DIR", str(tmp_path))`）

```python
def test_get_default_when_missing(client, tmp_path, monkeypatch):
    monkeypatch.setenv("AI_TRADER_DATA_DIR", str(tmp_path))
    assert client.get("/api/config/analysis").json()["signals"]["rsi_oversold"] == 30

def test_put_then_get_roundtrip(client, tmp_path, monkeypatch):
    monkeypatch.setenv("AI_TRADER_DATA_DIR", str(tmp_path))
    body = client.get("/api/config/analysis").json()
    body["signals"]["rsi_oversold"] = 25
    assert client.put("/api/config/analysis", json=body).status_code == 200
    assert client.get("/api/config/analysis").json()["signals"]["rsi_oversold"] == 25
    assert (tmp_path / "analysis_config.json").exists()
```

- [ ] **Step 2–5**：失败 → 实现 → 通过 → `git commit -m "feat(web): analysis preset GET/PUT"`

---

### Task 10: 前端脚手架、API 客户端、导航

**Files:**
- Create: `frontend/`（Vite react-ts 模板）+ `frontend/tailwind.config.js`、`frontend/postcss.config.js`、`frontend/src/index.css`
- Create: `frontend/src/api/types.ts`、`frontend/src/api/client.ts`、`frontend/src/App.tsx`、`frontend/src/components/Navbar.tsx`、`frontend/src/pages/DcaPage.tsx`（占位）、`frontend/src/pages/AnalysisPage.tsx`（占位）
- Modify: `frontend/vite.config.ts`（`server.proxy["/api"] = "http://127.0.0.1:8000"`，`test` 配置 jsdom）
- Test: `frontend/src/api/client.test.ts`

**Interfaces:**
- `types.ts`：与 Task 5–9 的 Pydantic 模型逐字段对应的 TS 类型：`Bar, KlinesResponse, DCARequest, DCAResponse, IndicatorParams, SignalParams, DataRange, AnalysisRequest, AnalysisResponse, BacktestParams, BacktestRequest, BacktestResponse, AnalysisPreset`；并导出 `DEFAULT_INDICATORS`、`DEFAULT_SIGNALS`、`DEFAULT_BACKTEST` 常量，值与后端默认一致。
- `client.ts`：`api.getSymbols(mainstreamOnly: boolean)`, `api.getIntervals()`, `api.getKlines(range: DataRange)`, `api.calculateDca(req)`, `api.runAnalysis(req)`, `api.runBacktest(req)`, `api.getPreset()`, `api.savePreset(p)`；基于 `fetch`，非 2xx 时抛 `ApiError(status, detail)`（`detail` 取响应体 `detail` 字段）。
- `App.tsx`：`BrowserRouter` + `QueryClientProvider`；路由 `/dca`、`/analysis`，`/` 重定向 `/analysis`。
- `Navbar.tsx`：链接"定投计算"、"技术分析"；禁用项"策略管理"、"回测"、"监控"、"设置"（`aria-disabled`）。

- [ ] **Step 1: 脚手架**

Run（在仓库根）：
```bash
npm create vite@latest frontend -- --template react-ts
cd frontend && npm i && npm i react-router-dom @tanstack/react-query lightweight-charts && npm i -D tailwindcss @tailwindcss/vite vitest jsdom @testing-library/react @testing-library/jest-dom @playwright/test
```
Expected: `npm run dev` 能起来。

- [ ] **Step 2: 写失败测试**

```ts
// frontend/src/api/client.test.ts
import { describe, it, expect, vi } from "vitest";
import { api, ApiError } from "./client";

describe("api client", () => {
  it("throws ApiError with detail on 502", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "binance unreachable" }), { status: 502 })));
    await expect(api.getIntervals()).rejects.toMatchObject({ status: 502, detail: "binance unreachable" });
  });
  it("returns parsed json on 200", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ intervals: ["1d"] }), { status: 200 })));
    expect(await api.getIntervals()).toEqual({ intervals: ["1d"] });
  });
});
```

- [ ] **Step 3: 运行确认失败**：`cd frontend && npx vitest run` → 找不到模块
- [ ] **Step 4: 实现 types、client、App、Navbar、两个占位页**
- [ ] **Step 5: 运行通过**：`npx vitest run` 2 passed；`npm run build` 无类型错误
- [ ] **Step 6: Commit** `git add frontend && git commit -m "feat(frontend): Vite+React scaffold, API client, navbar"`

---

### Task 11: 定投页

**Files:**
- Create: `frontend/src/components/dca/DcaForm.tsx`、`frontend/src/components/dca/DcaResult.tsx`
- Modify: `frontend/src/pages/DcaPage.tsx`
- Test: `frontend/src/pages/DcaPage.test.tsx`

**Interfaces:**
- `DcaForm({ onSubmit: (req: DCARequest) => void, loading: boolean })`：交易对下拉（`useQuery(['symbols', mainstreamOnly], ...)`）、"仅显示主流货币"复选、金额（默认 200）、每月日期（默认 10）、开始日期（默认一年前）、结束日期（默认今天）。
- `DcaResult({ data: DCAResponse })`：汇总卡片（总投入、当前价值、收益、收益率、平均成本、累计币数）+ 明细表（日期、价格、买入币数）。
- `DcaPage`：`useMutation(api.calculateDca)`；错误用红色提示条显示 `ApiError.detail`。

- [ ] **Step 1: 写失败测试**（用 `vi.spyOn(api, ...)` mock）

```tsx
it("renders summary after calculate", async () => {
  vi.spyOn(api, "getSymbols").mockResolvedValue({ symbols: ["BTCUSDT"] });
  vi.spyOn(api, "calculateDca").mockResolvedValue({ symbol: "BTCUSDT", total_invested: 400, total_coins: 0.01, current_price: 50000, total_value: 500, profit: 100, profit_rate: 25, average_cost: 40000, investment_count: 2, records: [] });
  render(<Providers><DcaPage /></Providers>);
  await userEvent.click(await screen.findByRole("button", { name: "计算收益" }));
  expect(await screen.findByText("25.00%")).toBeInTheDocument();
});
```

- [ ] **Step 2–5**：失败 → 实现 → `npx vitest run` 通过 → `git commit -m "feat(frontend): DCA page"`

---

### Task 12: 技术分析页

**Files:**
- Create: `frontend/src/components/analysis/ParamPanel.tsx`（五个折叠组：`DataGroup`、`IndicatorGroup`、`PatternGroup`、`SignalGroup`、`BacktestGroup` 各一个文件同目录）
- Create: `frontend/src/components/analysis/PriceChart.tsx`、`frontend/src/components/analysis/ResultTabs.tsx`
- Modify: `frontend/src/pages/AnalysisPage.tsx`
- Test: `frontend/src/components/analysis/PriceChart.test.tsx`、`frontend/src/pages/AnalysisPage.test.tsx`

**Interfaces:**
- 页面状态（`AnalysisPage` 内 `useState`）：`range: DataRange`、`indicators: IndicatorParams`、`signals: SignalParams`、`backtest: BacktestParams`、`enabledPatterns: Set<string>`（仅前端过滤显示，与 Tkinter 一致不影响信号）。
- 查询：`klines = useQuery(['klines', range], ...)` 由"加载数据"按钮触发（`enabled: false` + `refetch`）；`analysis = useMutation(api.runAnalysis)`；`bt = useMutation(api.runBacktest)`；预设 `useQuery(['preset'])` + `useMutation(api.savePreset)`。
- `PriceChart({ bars: Bar[], indicators?: AnalysisResponse["indicators"], entry?: number[], exit?: number[] })`：lightweight-charts `createChart`；主图 `addCandlestickSeries` + `addHistogramSeries`（成交量，独立 priceScale）+ 对每个 `sma_*`/`bb_*` 键 `addLineSeries`；`rsi`、`macd_*`、`kdj_*` 各自一个 pane（用三个独立 `createChart` 竖排并用 `timeScale().subscribeVisibleLogicalRangeChange` 同步）；入场/出场 `setMarkers`（`belowBar` 绿色 arrowUp / `aboveBar` 红色 arrowDown）。`null` 值在喂入前过滤掉。
- `ResultTabs({ analysis?: AnalysisResponse, backtest?: BacktestResponse, bars: Bar[] })`：三个 tab：分析结果（入场/出场数量 + effectiveness 表）、信号详情（入场/出场时间与当根 close 的表，最多 20 行）、回测结果（指标卡片 + trades 表）。
- 错误：任一请求失败在面板顶部显示 `ApiError.detail`。

- [ ] **Step 1: 写失败测试**

```tsx
// PriceChart.test.tsx — lightweight-charts 在 jsdom 里不能真正渲染，mock 模块：
vi.mock("lightweight-charts", () => ({ createChart: vi.fn(() => ({ addCandlestickSeries: vi.fn(() => ({ setData: vi.fn(), setMarkers: vi.fn() })), addHistogramSeries: vi.fn(() => ({ setData: vi.fn(), priceScale: () => ({ applyOptions: vi.fn() }) })), addLineSeries: vi.fn(() => ({ setData: vi.fn() })), timeScale: () => ({ subscribeVisibleLogicalRangeChange: vi.fn(), setVisibleLogicalRange: vi.fn() }), remove: vi.fn(), applyOptions: vi.fn() })) }));
it("adds one line series per indicator key and skips nulls", () => { /* 断言 addLineSeries 调用次数 == 指标键数，setData 的数组不含 null */ });

// AnalysisPage.test.tsx
it("shows 502 detail when klines fail", async () => {
  vi.spyOn(api, "getSymbols").mockResolvedValue({ symbols: ["BTCUSDT"] });
  vi.spyOn(api, "getIntervals").mockResolvedValue({ intervals: ["1d"] });
  vi.spyOn(api, "getPreset").mockResolvedValue(DEFAULT_PRESET);
  vi.spyOn(api, "getKlines").mockRejectedValue(new ApiError(502, "binance unreachable"));
  render(<Providers><AnalysisPage /></Providers>);
  await userEvent.click(await screen.findByRole("button", { name: "加载数据" }));
  expect(await screen.findByText("binance unreachable")).toBeInTheDocument();
});
```

- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现五个参数组、PriceChart、ResultTabs、页面编排**
- [ ] **Step 4: `npx vitest run` 通过；`npm run build` 无错**
- [ ] **Step 5: 手动联调**：后端 `uv run ai-trader-web`，前端 `npm run dev`，浏览器 `http://localhost:5173/analysis` 加载 BTCUSDT 1d 一年数据 → 分析 → 回测，三个 tab 有内容。
- [ ] **Step 6: Commit** `git commit -m "feat(frontend): technical analysis page with lightweight-charts"`

---

### Task 13: Playwright 端到端

**Files:**
- Create: `frontend/playwright.config.ts`、`frontend/e2e/analysis.spec.ts`、`frontend/e2e/fixtures/*.json`（symbols、intervals、preset、klines 30 根、analysis、backtest 各一份静态响应）
- Modify: `frontend/package.json`（`"test:e2e": "playwright test"`）

**Interfaces:** `playwright.config.ts` 用 `webServer: { command: "npm run dev", port: 5173 }`；用 `page.route("**/api/**", ...)` 按路径返回夹具，不启动后端。

- [ ] **Step 1: 写用例**

```ts
test("load → analyze → backtest", async ({ page }) => {
  // route 每个 /api/* 到夹具
  await page.goto("/analysis");
  await page.getByRole("button", { name: "加载数据" }).click();
  await page.getByRole("button", { name: "开始分析" }).click();
  await expect(page.getByRole("tab", { name: "分析结果" })).toBeVisible();
  await page.getByRole("button", { name: "运行回测" }).click();
  await page.getByRole("tab", { name: "回测结果" }).click();
  await expect(page.getByText("总交易次数")).toBeVisible();
});

test("shows error when backend is down", async ({ page }) => {
  await page.route("**/api/market/klines*", r => r.fulfill({ status: 502, json: { detail: "binance unreachable" } }));
  await page.goto("/analysis");
  await page.getByRole("button", { name: "加载数据" }).click();
  await expect(page.getByText("binance unreachable")).toBeVisible();
});
```

- [ ] **Step 2: `npx playwright install chromium`，运行确认失败/通过**：`npm run test:e2e`
- [ ] **Step 3: 修到通过**
- [ ] **Step 4: Commit** `git commit -m "test(frontend): Playwright e2e for analysis flow"`

---

### Task 14: 生产托管、README、最终验收

**Files:**
- Modify: `src/ai_trader/web/app.py`（已在 Task 4 实现 dist 挂载；此处验证）
- Modify: `README.md`、`QUICK_START.md`
- Test: `tests/web/test_static.py`

**Interfaces:** 无新增。

- [ ] **Step 1: 写测试**：`tmp_path` 下造 `frontend/dist/index.html`，`monkeypatch` 让 `create_app()` 用该目录（给 `create_app(dist_dir: Path | None = None)` 加可选参数），断言 `GET /` 返回该 HTML 且 `GET /api/health` 仍 200。
- [ ] **Step 2–3**：失败 → 实现 → 通过。
- [ ] **Step 4: 构建并单进程验证**：`cd frontend && npm run build && cd .. && uv run ai-trader-web &`，浏览器打开 `http://127.0.0.1:8000/` 完成 spec 第 1 节的验收流程；对比同一参数下 Tkinter 版（`uv run ai-trader-gui`）的回测数字一致。
- [ ] **Step 5: 更新 README / QUICK_START**：新增"网页版（推荐）"一节：`uv sync --group dev`、`cd frontend && npm i && npm run build`、`uv run ai-trader-web`；开发模式两条命令；把 Tkinter 入口标为"旧版"。
- [ ] **Step 6: 全量测试**：`uv run pytest -q` 与 `cd frontend && npx vitest run && npm run test:e2e` 全绿。
- [ ] **Step 7: Commit** `git commit -m "feat(web): serve built frontend; docs for web entry"`
