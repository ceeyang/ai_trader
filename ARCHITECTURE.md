# AI数字货币量化交易系统 - 架构文档

## 项目概述

本项目是一个基于Python的AI数字货币量化交易系统，采用模块化架构设计，支持策略开发、回测、模拟交易、实盘交易和监控通知。

## 架构设计原则

### 1. 模块化设计
- **单一职责**: 每个模块只负责一个特定功能
- **松耦合**: 模块间通过接口和抽象类交互
- **高内聚**: 相关功能组织在同一模块内

### 2. 可扩展性
- **插件化**: 支持动态加载策略和数据源
- **配置驱动**: 通过配置文件管理参数
- **接口标准化**: 统一的接口规范

### 3. 可测试性
- **依赖注入**: 便于单元测试
- **模拟支持**: 支持Mock和Stub
- **测试覆盖**: 完整的测试框架

## 核心模块架构

### 1. 基础层 (Core Layer)

#### BaseStrategy (策略基类)
```python
class BaseStrategy(ABC):
    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame
    def calculate_position_size(self, signal: Dict, price: float) -> float
    def on_data(self, data: pd.DataFrame) -> List[Dict]
```

#### BaseDataSource (数据源基类)
```python
class BaseDataSource(ABC):
    def get_historical_data(self, symbol: str, interval: str, 
                           start_time: datetime, end_time: datetime) -> pd.DataFrame
    def get_current_price(self, symbol: str) -> float
    def get_available_symbols(self) -> List[str]
```

#### BaseBroker (经纪商基类)
```python
class BaseBroker(ABC):
    def place_order(self, order: Order) -> str
    def cancel_order(self, order_id: str) -> bool
    def get_balance(self) -> Dict[str, float]
```

### 2. 数据层 (Data Layer)

#### 数据提供商
- **BinanceDataSource**: 币安数据源实现
- **OKXDataSource**: OKX数据源实现（待开发）
- **BaseDataSource**: 数据源基类

#### 数据存储
- **Database**: SQLite/PostgreSQL支持
- **Cache**: Redis缓存支持
- **File**: 本地文件存储

### 3. 策略层 (Strategy Layer)

#### 定投策略 (DCA)
```python
class DCAStrategy(BaseStrategy):
    def __init__(self, symbol: str, invest_amount: float, 
                 invest_day: int, start_date: datetime, end_date: datetime)
    def execute_dca(self) -> Dict[str, Any]
```

#### AI策略 (待开发)
- **MLStrategy**: 机器学习策略
- **DeepLearningStrategy**: 深度学习策略
- **ReinforcementLearningStrategy**: 强化学习策略

#### 技术分析策略 (待开发)
- **SMAStrategy**: 简单移动平均策略
- **RSIStrategy**: RSI策略
- **BollingerStrategy**: 布林带策略

### 4. 交易层 (Trading Layer)

#### 经纪商实现
- **BinanceBroker**: 币安经纪商
- **OKXBroker**: OKX经纪商（待开发）

#### 风险管理
- **PositionManager**: 仓位管理
- **RiskManager**: 风险管理
- **OrderManager**: 订单管理

### 5. 回测层 (Backtesting Layer)

#### 回测引擎
```python
class BacktestEngine:
    def run_backtest(self, strategy: BaseStrategy, 
                    start_date: datetime, end_date: datetime) -> BacktestResult
```

#### 回测指标
- **SharpeRatio**: 夏普比率
- **MaxDrawdown**: 最大回撤
- **WinRate**: 胜率
- **ProfitFactor**: 盈利因子

### 6. 监控层 (Monitoring Layer)

#### 告警系统
- **EmailAlert**: 邮件告警
- **TelegramAlert**: Telegram告警
- **WebhookAlert**: Webhook告警

#### 监控面板
- **Dashboard**: 实时监控面板
- **Metrics**: 性能指标
- **Logs**: 日志管理

## 配置管理

### 配置文件结构
```yaml
# config/settings.yaml
app:
  name: "AI Trader"
  version: "0.1.0"
  debug: false

data_sources:
  binance:
    base_url: "https://api.binance.com/api/v3"
    timeout: 10
    rate_limit_delay: 0.1

trading:
  default_currency: "USDT"
  min_order_amount: 10.0
  max_order_amount: 10000.0

strategies:
  dca:
    default_invest_amount: 200
    default_invest_day: 10
```

### 配置管理类
```python
class ConfigManager:
    def get(self, key: str, default: Any = None) -> Any
    def set(self, key: str, value: Any) -> None
    def load_config(self) -> None
    def save_config(self) -> None
```

## 数据流架构

### 1. 数据获取流程
```
数据源 → 数据提供商 → 数据处理器 → 数据存储 → 策略引擎
```

### 2. 策略执行流程
```
市场数据 → 策略信号 → 风险管理 → 订单执行 → 持仓更新
```

### 3. 回测流程
```
历史数据 → 策略回放 → 信号生成 → 模拟交易 → 结果分析
```

## 扩展性设计

### 1. 添加新策略
1. 继承 `BaseStrategy` 类
2. 实现必要的方法
3. 在策略注册表中注册
4. 添加配置参数

### 2. 添加新数据源
1. 继承 `BaseDataSource` 类
2. 实现API接口
3. 添加数据解析逻辑
4. 更新配置

### 3. 添加新经纪商
1. 继承 `BaseBroker` 类
2. 实现交易接口
3. 添加认证逻辑
4. 更新配置

## 测试架构

### 1. 单元测试
- **策略测试**: 测试策略逻辑
- **数据源测试**: 测试数据获取
- **经纪商测试**: 测试交易功能

### 2. 集成测试
- **API集成**: 测试外部API
- **数据库集成**: 测试数据存储
- **端到端测试**: 测试完整流程

### 3. 性能测试
- **压力测试**: 测试系统负载
- **并发测试**: 测试多线程性能
- **内存测试**: 测试内存使用

## 部署架构

### 1. 开发环境
```bash
# 安装依赖
pip install -r requirements.txt

# 运行测试
pytest

# 启动GUI
python -m ai_trader.gui.main_window
```

### 2. 生产环境
```bash
# 安装包
pip install ai-trader

# 配置服务
systemctl enable ai-trader

# 启动服务
systemctl start ai-trader
```

### 3. Docker部署
```dockerfile
FROM python:3.9-slim
COPY . /app
WORKDIR /app
RUN pip install -r requirements.txt
CMD ["python", "-m", "ai_trader.gui.main_window"]
```

## 安全考虑

### 1. API密钥管理
- 环境变量存储
- 加密存储
- 访问控制

### 2. 数据安全
- 数据加密
- 访问日志
- 备份策略

### 3. 交易安全
- 风险控制
- 订单验证
- 异常处理

## 性能优化

### 1. 数据缓存
- Redis缓存
- 内存缓存
- 文件缓存

### 2. 异步处理
- 异步数据获取
- 异步订单处理
- 异步通知发送

### 3. 数据库优化
- 索引优化
- 查询优化
- 连接池

## 监控和日志

### 1. 日志系统
- 结构化日志
- 日志级别
- 日志轮转

### 2. 监控指标
- 系统指标
- 业务指标
- 性能指标

### 3. 告警机制
- 阈值告警
- 异常告警
- 趋势告警

## 未来规划

### 1. 短期目标
- 完善现有功能
- 添加更多策略
- 优化用户体验

### 2. 中期目标
- AI策略集成
- 多交易所支持
- 云部署支持

### 3. 长期目标
- 分布式架构
- 微服务化
- 智能运维
