"""
定投策略实现

基于原有定投计算逻辑重构的策略类。
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
import pandas as pd

from ...core.base.strategy import BaseStrategy
from ...core.data.providers import BinanceDataSource
from .plan import Allocation, DCAPlan, run_dca_plan


class DCAStrategy(BaseStrategy):
    """
    定投策略
    
    实现定期投资策略，支持自定义投资日期和金额。
    """
    
    def __init__(self, symbol: str, invest_amount: float, invest_day: int,
                 start_date: datetime, end_date: datetime, 
                 config: Optional[Dict[str, Any]] = None) -> None:
        """
        初始化定投策略
        
        Args:
            symbol: 交易对符号
            invest_amount: 每次投资金额
            invest_day: 投资日期（每月几号）
            start_date: 开始日期
            end_date: 结束日期
            config: 额外配置参数
        """
        super().__init__(f"DCA_{symbol}", config)
        
        self.symbol: str = symbol
        self.invest_amount: float = invest_amount
        self.invest_day: int = invest_day
        self.start_date: datetime = start_date
        self.end_date: datetime = end_date
        
        # 初始化数据源
        self.data_source = BinanceDataSource()
        
        # 投资记录
        self.investment_records: List[Dict[str, Any]] = []
        self.total_invested: float = 0.0
        self.total_coins: float = 0.0
        
    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        生成定投信号
        
        Args:
            data: 市场数据（对于定投策略，这个参数通常不使用）
            
        Returns:
            交易信号DataFrame
        """
        # 定投策略不需要基于市场数据生成信号
        # 信号在初始化时就已经确定
        return pd.DataFrame()
    
    def calculate_position_size(self, signal: Dict[str, Any], price: float) -> float:
        """
        计算仓位大小（定投固定金额）
        
        Args:
            signal: 交易信号
            price: 当前价格
            
        Returns:
            仓位大小
        """
        return self.invest_amount / price
    
    def execute_dca(self) -> Dict[str, Any]:
        """
        执行定投策略（单币种、每月；内部委托给 run_dca_plan，按区间取数）

        Returns:
            定投结果
        """
        if not self.data_source.connect():
            raise ConnectionError("无法连接到数据源")

        try:
            plan = DCAPlan(
                frequency="monthly",
                amount=self.invest_amount,
                start=self.start_date,
                end=self.end_date,
                allocations=[Allocation(self.symbol, 1.0)],
                invest_day=self.invest_day,
            )
            result = run_dca_plan(plan, self.data_source)
            leg = result["legs"][0]
            self.investment_records = leg["records"]
            self.total_coins = leg["total_coins"]
            self.total_invested = leg["total_invested"]
            return {
                'symbol': self.symbol,
                'total_invested': leg["total_invested"],
                'total_coins': leg["total_coins"],
                'current_price': leg["current_price"],
                'total_value': leg["total_value"],
                'profit': leg["profit"],
                'profit_rate': leg["profit_rate"],
                'average_cost': leg["average_cost"],
                'investment_count': leg["investment_count"],
                'records': leg["records"],
            }

        finally:
            self.data_source.disconnect()

    def get_investment_summary(self) -> Dict[str, Any]:
        """
        获取投资摘要
        
        Returns:
            投资摘要信息
        """
        return {
            'strategy_name': self.name,
            'symbol': self.symbol,
            'invest_amount': self.invest_amount,
            'invest_day': self.invest_day,
            'start_date': self.start_date.strftime('%Y-%m-%d'),
            'end_date': self.end_date.strftime('%Y-%m-%d'),
            'total_invested': self.total_invested,
            'total_coins': self.total_coins,
            'investment_count': len(self.investment_records),
        }
