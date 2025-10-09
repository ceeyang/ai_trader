"""
AI数字货币量化交易系统

一个基于Python的AI数字货币量化交易系统，支持策略开发、回测、模拟交易、实盘交易和监控通知。

主要功能:
- 多数据源支持 (币安、OKX等)
- 策略开发框架
- 回测引擎
- 模拟交易
- 实盘交易
- 风险管理
- 监控告警
- GUI界面
"""

__version__ = "0.1.0"
__author__ = "AI Trader Team"
__email__ = "team@aitrader.com"

# 导入核心模块
from .core.base.strategy import BaseStrategy
from .core.base.data_source import BaseDataSource
from .core.base.broker import BaseBroker

__all__ = [
    "BaseStrategy",
    "BaseDataSource", 
    "BaseBroker",
]
