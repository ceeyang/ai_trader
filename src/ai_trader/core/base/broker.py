"""
经纪商基类

定义所有经纪商的基础接口。
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from datetime import datetime
from enum import Enum


class OrderType(Enum):
    """订单类型"""
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class OrderSide(Enum):
    """订单方向"""
    BUY = "buy"
    SELL = "sell"


class OrderStatus(Enum):
    """订单状态"""
    PENDING = "pending"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class Order:
    """订单类"""
    
    def __init__(self, symbol: str, side: OrderSide, order_type: OrderType,
                 quantity: float, price: Optional[float] = None) -> None:
        self.symbol: str = symbol
        self.side: OrderSide = side
        self.order_type: OrderType = order_type
        self.quantity: float = quantity
        self.price: Optional[float] = price
        self.status: OrderStatus = OrderStatus.PENDING
        self.filled_quantity: float = 0.0
        self.remaining_quantity: float = quantity
        self.timestamp: datetime = datetime.now()
        self.order_id: Optional[str] = None


class BaseBroker(ABC):
    """
    经纪商基类
    
    所有经纪商都应该继承此基类并实现必要的方法。
    """
    
    def __init__(self, name: str, config: Optional[Dict[str, Any]] = None) -> None:
        """
        初始化经纪商
        
        Args:
            name: 经纪商名称
            config: 经纪商配置参数
        """
        self.name: str = name
        self.config: Dict[str, Any] = config or {}
        self.is_connected: bool = False
        
    @abstractmethod
    def connect(self) -> bool:
        """
        连接到经纪商
        
        Returns:
            连接是否成功
        """
        pass
    
    @abstractmethod
    def disconnect(self) -> None:
        """断开经纪商连接"""
        pass
    
    @abstractmethod
    def place_order(self, order: Order) -> str:
        """
        下单
        
        Args:
            order: 订单对象
            
        Returns:
            订单ID
        """
        pass
    
    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """
        取消订单
        
        Args:
            order_id: 订单ID
            
        Returns:
            是否成功取消
        """
        pass
    
    @abstractmethod
    def get_order_status(self, order_id: str) -> OrderStatus:
        """
        获取订单状态
        
        Args:
            order_id: 订单ID
            
        Returns:
            订单状态
        """
        pass
    
    @abstractmethod
    def get_balance(self) -> Dict[str, float]:
        """
        获取账户余额
        
        Returns:
            余额字典
        """
        pass
    
    @abstractmethod
    def get_positions(self) -> Dict[str, float]:
        """
        获取持仓信息
        
        Returns:
            持仓字典
        """
        pass
    
    def get_account_info(self) -> Dict[str, Any]:
        """
        获取账户信息
        
        Returns:
            账户信息
        """
        return {
            'balance': self.get_balance(),
            'positions': self.get_positions(),
            'is_connected': self.is_connected,
        }
