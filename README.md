# AI数字货币量化交易系统

一个基于Python的AI数字货币量化交易系统，支持策略开发、回测、模拟交易、实盘交易和监控通知。

## 功能特性

- 🌍 **跨平台支持**: 支持Windows、macOS、Linux
- 💰 **多币种支持**: 支持所有币安USDT交易对
- 📅 **灵活日期选择**: 自定义开始和结束日期
- 🗓️ **定投日期设置**: 选择每月定投的具体日期
- 💵 **实时价格**: 使用当前市场价格计算收益
- 📊 **详细报告**: 显示完整的定投历史和收益分析
- 🤖 **AI策略**: 支持机器学习策略开发
- 📈 **回测引擎**: 完整的策略回测功能
- 🎯 **风险管理**: 内置风险管理模块
- 📊 **技术分析**: 完整的技术指标和K线形态识别
- 🔍 **信号检测**: 智能交易信号生成和验证
- 📱 **GUI界面**: 现代化的用户界面
- 🔧 **CLI工具**: 命令行接口支持

## 项目结构

```text
ai_trader/
├── src/ai_trader/           # 主源代码
│   ├── core/               # 核心模块
│   │   ├── base/           # 基础类
│   │   ├── data/           # 数据模块
│   │   ├── analysis/       # 技术分析模块
│   │   ├── trading/        # 交易模块
│   │   └── utils/          # 工具模块
│   ├── strategies/         # 策略模块
│   │   ├── dca/           # 定投策略
│   │   ├── ai/            # AI策略
│   │   └── technical/     # 技术分析策略
│   ├── backtesting/       # 回测模块
│   ├── simulation/        # 模拟交易
│   ├── monitoring/        # 监控模块
│   └── gui/               # GUI模块
├── config/                # 配置文件
├── tests/                 # 测试文件
├── docs/                  # 文档
└── examples/              # 示例代码
```

## 安装要求

### Python版本

- Python 3.8 或更高版本

### 依赖包

```bash
pip install -r requirements.txt
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 启动GUI应用

```bash
python -m ai_trader.gui.main_window
```

### 3. 使用CLI工具

```bash
# 定投收益计算
python -m ai_trader.cli dca --symbol BTCUSDT --amount 200 --day 10 --start-date 2024-01-01

# 策略管理
python -m ai_trader.cli strategy --list

# 回测
python -m ai_trader.cli backtest --strategy DCA --start-date 2024-01-01 --end-date 2024-12-31
```

## 技术分析模块

### 功能特性

- **技术指标计算**: 移动平均线、MACD、RSI、KDJ、布林带等
- **K线形态识别**: 锤子线、十字星、吞没形态、启明星等
- **交易信号检测**: 综合多种信号生成入场和出场信号
- **回测分析**: 测试策略的历史表现和参数优化

### 使用示例

```python
from src.ai_trader.core.analysis import TechnicalIndicators, SignalDetector, BacktestEngine

# 计算技术指标
indicators = TechnicalIndicators(data)
sma_20 = indicators.sma(20)
rsi = indicators.rsi(14)
macd_dif, macd_dea, macd_hist = indicators.macd()

# 检测交易信号
signal_detector = SignalDetector(data)
entry_signals = signal_detector.get_comprehensive_entry_signals()
exit_signals = signal_detector.get_comprehensive_exit_signals()

# 运行回测
backtest_engine = BacktestEngine(data, initial_capital=100000)
result = backtest_engine.run_backtest()
```

详细使用说明请参考 [技术分析指南](TECHNICAL_ANALYSIS_GUIDE.md)。

## 使用方法

### GUI界面

1. **启动应用**: 运行 `python -m ai_trader.gui.main_window`
2. **选择币种**: 从下拉列表中选择要定投的加密货币
3. **设置参数**: 配置定投日期、金额和时间范围
4. **计算收益**: 点击"计算收益"按钮查看结果

### 命令行工具

#### 定投计算

```bash
python -m ai_trader.cli dca \
  --symbol BTCUSDT \
  --amount 200 \
  --day 10 \
  --start-date 2024-01-01 \
  --end-date 2024-12-31
```

#### 策略管理

```bash
# 列出可用策略
python -m ai_trader.cli strategy --list

# 运行策略
python -m ai_trader.cli strategy --run DCA
```

#### 回测

```bash
python -m ai_trader.cli backtest \
  --strategy DCA \
  --start-date 2024-01-01 \
  --end-date 2024-12-31 \
  --initial-capital 10000
```

## 配置

系统使用YAML配置文件进行配置管理，配置文件位于 `config/settings.yaml`。

### 主要配置项

- **数据源配置**: 配置各种交易所API
- **交易配置**: 设置交易参数和风险管理
- **策略配置**: 配置各种策略参数
- **监控配置**: 设置告警和通知

## 开发指南

### 添加新策略

1. 在 `src/ai_trader/strategies/` 下创建新策略目录
2. 继承 `BaseStrategy` 类
3. 实现必要的方法
4. 添加测试用例

### 添加新数据源

1. 在 `src/ai_trader/core/data/providers/` 下创建新数据源
2. 继承 `BaseDataSource` 类
3. 实现必要的方法
4. 添加测试用例

### 运行测试

```bash
# 运行所有测试
pytest

# 运行特定测试
pytest tests/unit/test_dca_strategy.py

# 生成覆盖率报告
pytest --cov=src/ai_trader --cov-report=html
```

## 架构设计

### 核心模块

- **BaseStrategy**: 策略基类，定义策略接口
- **BaseDataSource**: 数据源基类，定义数据获取接口
- **BaseBroker**: 经纪商基类，定义交易接口

### 设计原则

1. **单一职责**: 每个模块只负责一个特定功能
2. **依赖注入**: 通过接口和抽象类实现松耦合
3. **配置驱动**: 通过配置文件管理参数
4. **可测试性**: 每个模块都有对应的测试
5. **可扩展性**: 易于添加新的策略和数据源

## 技术栈

- **核心语言**: Python 3.8+
- **GUI框架**: tkinter (跨平台)
- **数据处理**: pandas, numpy
- **机器学习**: scikit-learn, tensorflow/pytorch
- **数据库**: SQLite/PostgreSQL
- **API**: requests, websockets
- **测试**: pytest
- **日志**: logging
- **配置**: pyyaml

## 贡献指南

1. Fork 项目
2. 创建功能分支
3. 提交更改
4. 推送到分支
5. 创建 Pull Request

## 许可证

MIT License

## 联系方式

- 项目主页: <https://github.com/ai-trader/ai-trader>
- 问题反馈: <https://github.com/ai-trader/ai-trader/issues>
- 邮箱: <team@aitrader.com>

## 更新日志

### v0.1.0 (2024-01-01)

- 初始版本发布
- 支持定投策略
- 基础GUI界面
- CLI工具
- 币安数据源集成
