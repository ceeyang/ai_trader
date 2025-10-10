# 技术分析模块使用指南

## 概述

本技术分析模块提供了完整的金融技术分析功能，包括：

1. **技术指标计算** - 移动平均线、MACD、RSI、KDJ、布林带等
2. **K线形态识别** - 锤子线、十字星、吞没形态、启明星等
3. **交易信号检测** - 综合多种信号生成入场和出场信号
4. **回测分析** - 测试策略的历史表现和参数优化

## 模块结构

```
src/ai_trader/core/analysis/
├── __init__.py          # 模块初始化
├── indicators.py         # 技术指标计算
├── patterns.py          # K线形态识别
├── signals.py           # 交易信号检测
└── backtest.py          # 回测分析引擎
```

## 快速开始

### 1. 基本使用

```python
from src.ai_trader.core.analysis import TechnicalIndicators, CandlestickPatterns, SignalDetector, BacktestEngine

# 假设你已经有了历史数据 DataFrame
data = pd.DataFrame(...)  # 包含 'open', 'high', 'low', 'close', 'volume' 列

# 计算技术指标
indicators = TechnicalIndicators(data)
sma_20 = indicators.sma(20)
rsi = indicators.rsi(14)
macd_dif, macd_dea, macd_hist = indicators.macd()

# 识别K线形态
patterns = CandlestickPatterns(data)
hammer_signals = patterns.hammer()
doji_signals = patterns.doji()

# 检测交易信号
signal_detector = SignalDetector(data)
entry_signals = signal_detector.get_comprehensive_entry_signals()
exit_signals = signal_detector.get_comprehensive_exit_signals()

# 运行回测
backtest_engine = BacktestEngine(data, initial_capital=100000)
result = backtest_engine.run_backtest()
```

### 2. 获取历史数据

```python
from src.ai_trader.core.data.providers.binance import BinanceDataSource
from datetime import datetime, timedelta

# 连接数据源
data_source = BinanceDataSource()
data_source.connect()

# 获取历史数据
end_time = datetime.now()
start_time = end_time - timedelta(days=90)
data = data_source.get_historical_data(
    symbol='BTCUSDT',
    interval='1d',
    start_time=start_time,
    end_time=end_time
)
```

## 技术指标详解

### 移动平均线 (MA)

```python
# 简单移动平均线
sma_20 = indicators.sma(20)
sma_50 = indicators.sma(50)

# 指数移动平均线
ema_12 = indicators.ema(12)
ema_26 = indicators.ema(26)
```

### MACD指标

```python
# 计算MACD
dif, dea, macd_hist = indicators.macd(fast_period=12, slow_period=26, signal_period=9)

# 判断信号
# 金叉：dif > dea 且 dif上穿dea
# 死叉：dif < dea 且 dif下穿dea
```

### RSI相对强弱指数

```python
# 计算RSI
rsi = indicators.rsi(14)

# 判断信号
# 超卖：rsi < 30
# 超买：rsi > 70
```

### KDJ随机指标

```python
# 计算KDJ
k, d, j = indicators.kdj(k_period=9, d_period=3, j_period=3)

# 判断信号
# 金叉：k > d 且 k上穿d
# 死叉：k < d 且 k下穿d
```

### 布林带

```python
# 计算布林带
bb_upper, bb_middle, bb_lower = indicators.bollinger_bands(period=20, std_dev=2)

# 判断信号
# 下轨支撑：价格触及下轨
# 上轨压力：价格触及上轨
```

## K线形态识别

### 单根K线形态

```python
# 锤子线（看涨）
hammer_signals = patterns.hammer()

# 上吊线（看跌）
hanging_man_signals = patterns.hanging_man()

# 十字星
doji_signals = patterns.doji()
```

### 两根K线形态

```python
# 看涨吞没
bullish_engulfing = patterns.engulfing_bullish()

# 看跌吞没
bearish_engulfing = patterns.engulfing_bearish()
```

### 三根K线形态

```python
# 启明星（看涨）
morning_star = patterns.morning_star()

# 黄昏星（看跌）
evening_star = patterns.evening_star()

# 红三兵（看涨）
three_white_soldiers = patterns.three_white_soldiers()

# 三只乌鸦（看跌）
three_black_crows = patterns.three_black_crows()
```

## 交易信号检测

### 综合信号

```python
# 获取综合入场信号
entry_signals = signal_detector.get_comprehensive_entry_signals()

# 获取综合出场信号
exit_signals = signal_detector.get_comprehensive_exit_signals()

# 找到信号点
entry_points, exit_points = signal_detector.find_signal_points()
```

### 具体信号类型

```python
# MACD信号
macd_bullish, macd_bearish = signal_detector.get_macd_signals()

# RSI信号
rsi_bullish, rsi_bearish = signal_detector.get_rsi_signals(oversold=30, overbought=70)

# KDJ信号
kdj_bullish, kdj_bearish = signal_detector.get_kdj_signals()

# 布林带信号
bb_bullish, bb_bearish = signal_detector.get_bollinger_signals()

# 突破信号
breakout_up, breakout_down = signal_detector.get_breakout_signals()
```

### 趋势判断

```python
# 判断趋势方向
trend = signal_detector.get_trend_direction(short_period=20, long_period=50)
# 1: 上涨趋势, -1: 下跌趋势, 0: 震荡

# 获取信号强度
signal_strength = signal_detector.get_signal_strength(entry_signals)
```

## 回测分析

### 基本回测

```python
# 创建回测引擎
backtest_engine = BacktestEngine(data, initial_capital=100000)

# 运行回测
result = backtest_engine.run_backtest()

# 查看结果
print(f"总交易次数: {result.total_trades}")
print(f"胜率: {result.win_rate:.2%}")
print(f"总收益率: {result.total_return:.2%}")
print(f"最大回撤: {result.max_drawdown:.2f}")
print(f"夏普比率: {result.sharpe_ratio:.2f}")
```

### 自定义信号回测

```python
# 使用自定义信号
custom_entry_signals = signal_detector.get_rsi_signals()[0]
custom_exit_signals = signal_detector.get_rsi_signals()[1]

result = backtest_engine.run_backtest(
    entry_signals=custom_entry_signals,
    exit_signals=custom_exit_signals,
    position_size=0.1  # 每次交易10%仓位
)
```

### 信号有效性分析

```python
# 分析信号有效性
signal_analysis = backtest_engine.analyze_signal_effectiveness()

for signal_name, analysis in signal_analysis.items():
    print(f"{signal_name}:")
    print(f"  频率: {analysis['frequency']:.2%}")
    print(f"  平均1日收益: {analysis['avg_price_change_1d']:.2%}")
    print(f"  正收益比例: {analysis['positive_rate']:.2%}")
```

### 参数优化

```python
# 定义参数范围
param_ranges = {
    'rsi_oversold': [20, 25, 30, 35],
    'rsi_overbought': [65, 70, 75, 80]
}

# 优化参数
best_params = backtest_engine.optimize_parameters(param_ranges)
print(f"最优参数: {best_params}")
```

## 实际应用示例

### 1. 寻找交易机会

```python
# 获取数据
data_source = BinanceDataSource()
data_source.connect()
data = data_source.get_historical_data('BTCUSDT', '1d', start_time, end_time)

# 分析信号
signal_detector = SignalDetector(data)
entry_signals = signal_detector.get_comprehensive_entry_signals()

# 显示入场机会
entry_opportunities = data[entry_signals]
for date, row in entry_opportunities.iterrows():
    print(f"入场机会: {date.strftime('%Y-%m-%d')}, 价格: {row['close']:.2f}")
```

### 2. 策略验证

```python
# 运行回测
backtest_engine = BacktestEngine(data, initial_capital=100000)
result = backtest_engine.run_backtest()

# 生成报告
report = backtest_engine.generate_trading_report(result)
print(report)
```

### 3. 多币种分析

```python
symbols = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'ADAUSDT', 'SOLUSDT']
results = []

for symbol in symbols:
    data = data_source.get_historical_data(symbol, '1d', start_time, end_time)
    signal_detector = SignalDetector(data)
    backtest_engine = BacktestEngine(data, initial_capital=100000)
    result = backtest_engine.run_backtest()
    results.append((symbol, result.total_return, result.win_rate))

# 按收益率排序
results.sort(key=lambda x: x[1], reverse=True)
```

## 注意事项

1. **数据质量**: 确保历史数据完整且准确
2. **参数调优**: 不同市场环境需要调整参数
3. **风险控制**: 设置合理的止损和止盈
4. **信号确认**: 结合多个信号进行综合判断
5. **回测局限性**: 历史表现不代表未来收益

## 扩展功能

### 自定义指标

```python
class CustomIndicators(TechnicalIndicators):
    def custom_indicator(self, period=20):
        # 实现自定义指标
        return self.data['close'].rolling(period).mean()
```

### 自定义形态

```python
class CustomPatterns(CandlestickPatterns):
    def custom_pattern(self):
        # 实现自定义K线形态
        return self.data['close'] > self.data['open']
```

### 自定义信号

```python
class CustomSignalDetector(SignalDetector):
    def custom_entry_signal(self):
        # 实现自定义入场信号
        return self.get_rsi_signals()[0] & self.get_macd_signals()[0]
```

## 总结

本技术分析模块提供了完整的金融技术分析功能，可以帮助您：

1. **分析历史数据** - 计算各种技术指标和识别K线形态
2. **生成交易信号** - 综合多种信号生成入场和出场信号
3. **验证策略** - 通过回测验证策略的历史表现
4. **优化参数** - 通过参数优化提高策略效果

通过合理使用这些功能，您可以更好地理解市场走势，制定有效的交易策略。
