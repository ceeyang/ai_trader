"""
策略基类

定义所有交易策略的基础接口和通用功能。
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from datetime import datetime
import pandas as pd


class BaseStrategy(ABC):
    """
    策略基类
    
    所有交易策略都应该继承此基类并实现必要的方法。
    """
    
    def __init__(self, name: str, config: Optional[Dict[str, Any]] = None) -> None:
        """
        初始化策略
        
        Args:
            name: 策略名称
            config: 策略配置参数
        """
        self.name: str = name
        self.config: Dict[str, Any] = config or {}
        self.is_active: bool = False
        self.positions: Dict[str, float] = {}
        self.cash: float = 0.0
        
    @abstractmethod
    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        生成交易信号
        
        Args:
            data: 市场数据
            
        Returns:
            包含交易信号的DataFrame
        """
        pass
    
    @abstractmethod
    def calculate_position_size(self, signal: Dict[str, Any], price: float) -> float:
        """
        计算仓位大小
        
        Args:
            signal: 交易信号
            price: 当前价格
            
        Returns:
            仓位大小
        """
        pass
    
    def on_data(self, data: pd.DataFrame) -> List[Dict[str, Any]]:
        """
        处理新数据
        
        Args:
            data: 新的市场数据
            
        Returns:
            交易信号列表
        """
        if not self.is_active:
            return []
            
        signals = self.generate_signals(data)
        return self._process_signals(signals)
    
    def _process_signals(self, signals: pd.DataFrame) -> List[Dict[str, Any]]:
        """
        处理交易信号
        
        Args:
            signals: 交易信号DataFrame
            
        Returns:
            处理后的信号列表
        """
        processed_signals = []
        
        for _, signal in signals.iterrows():
            if signal.get('action') in ['buy', 'sell']:
                processed_signals.append({
                    'symbol': signal.get('symbol'),
                    'action': signal.get('action'),
                    'price': signal.get('price'),
                    'quantity': self.calculate_position_size(signal, signal.get('price')),
                    'timestamp': signal.get('timestamp', datetime.now()),
                })
        
        return processed_signals
    
    def start(self) -> None:
        """启动策略"""
        self.is_active = True
    
    def stop(self) -> None:
        """停止策略"""
        self.is_active = False
    
    def update_config(self, config: Dict[str, Any]) -> None:
        """
        更新策略配置
        
        Args:
            config: 新的配置参数
        """
        self.config.update(config)
    
    def get_status(self) -> Dict[str, Any]:
        """
        获取策略状态
        
        Returns:
            策略状态信息
        """
        return {
            'name': self.name,
            'is_active': self.is_active,
            'positions': self.positions.copy(),
            'cash': self.cash,
            'config': self.config.copy(),
        }
