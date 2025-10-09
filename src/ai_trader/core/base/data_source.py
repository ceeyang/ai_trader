"""
数据源基类

定义所有数据源的基础接口。
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
import pandas as pd


class BaseDataSource(ABC):
    """
    数据源基类
    
    所有数据源都应该继承此基类并实现必要的方法。
    """
    
    def __init__(self, name: str, config: Optional[Dict[str, Any]] = None) -> None:
        """
        初始化数据源
        
        Args:
            name: 数据源名称
            config: 数据源配置参数
        """
        self.name: str = name
        self.config: Dict[str, Any] = config or {}
        self.is_connected: bool = False
        
    @abstractmethod
    def connect(self) -> bool:
        """
        连接到数据源
        
        Returns:
            连接是否成功
        """
        pass
    
    @abstractmethod
    def disconnect(self) -> None:
        """断开数据源连接"""
        pass
    
    @abstractmethod
    def get_historical_data(self, symbol: str, interval: str, 
                           start_time: datetime, end_time: datetime) -> pd.DataFrame:
        """
        获取历史数据
        
        Args:
            symbol: 交易对符号
            interval: 时间间隔
            start_time: 开始时间
            end_time: 结束时间
            
        Returns:
            历史数据DataFrame
        """
        pass
    
    @abstractmethod
    def get_current_price(self, symbol: str) -> float:
        """
        获取当前价格
        
        Args:
            symbol: 交易对符号
            
        Returns:
            当前价格
        """
        pass
    
    def get_available_symbols(self) -> List[str]:
        """
        获取可用的交易对列表
        
        Returns:
            交易对列表
        """
        return []
    
    def get_supported_intervals(self) -> List[str]:
        """
        获取支持的时间间隔
        
        Returns:
            时间间隔列表
        """
        return ['1m', '5m', '15m', '1h', '4h', '1d']
    
    def is_symbol_supported(self, symbol: str) -> bool:
        """
        检查是否支持指定交易对
        
        Args:
            symbol: 交易对符号
            
        Returns:
            是否支持
        """
        return symbol in self.get_available_symbols()
    
    def get_status(self) -> Dict[str, Any]:
        """
        获取数据源状态
        
        Returns:
            状态信息
        """
        return {
            'name': self.name,
            'is_connected': self.is_connected,
            'config': self.config.copy(),
        }
