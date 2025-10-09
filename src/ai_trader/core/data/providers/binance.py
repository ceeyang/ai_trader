"""
币安数据源实现

基于币安API的数据源实现，重构原有代码。
"""

import requests
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import pandas as pd
import time

from .base import BaseDataSource


class BinanceDataSource(BaseDataSource):
    """
    币安数据源
    
    基于币安API实现的数据源，支持历史数据和实时价格获取。
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        """
        初始化币安数据源
        
        Args:
            config: 配置参数，可包含api_key, secret_key等
        """
        super().__init__("Binance", config)
        
        # API端点配置
        self.base_url = "https://api.binance.com/api/v3"
        self.klines_url = f"{self.base_url}/klines"
        self.ticker_url = f"{self.base_url}/ticker/price"
        self.exchange_info_url = f"{self.base_url}/exchangeInfo"
        
        # 请求配置
        self.timeout = self.config.get('timeout', 10)
        self.rate_limit_delay = self.config.get('rate_limit_delay', 0.1)
        
    def connect(self) -> bool:
        """
        连接到币安API
        
        Returns:
            连接是否成功
        """
        try:
            # 测试连接
            response = requests.get(f"{self.base_url}/ping", timeout=self.timeout)
            if response.status_code == 200:
                self.is_connected = True
                return True
            else:
                self.is_connected = False
                return False
        except Exception:
            self.is_connected = False
            return False
    
    def disconnect(self) -> None:
        """断开连接"""
        self.is_connected = False
    
    def get_historical_data(self, symbol: str, interval: str, 
                           start_time: datetime, end_time: datetime) -> pd.DataFrame:
        """
        获取历史K线数据
        
        Args:
            symbol: 交易对符号
            interval: 时间间隔
            start_time: 开始时间
            end_time: 结束时间
            
        Returns:
            历史数据DataFrame
        """
        if not self.is_connected:
            raise ConnectionError("数据源未连接")
        
        # 计算需要的数据量
        time_diff = end_time - start_time
        if interval == '1m':
            limit = min(int(time_diff.total_seconds() / 60), 1000)
        elif interval == '5m':
            limit = min(int(time_diff.total_seconds() / 300), 1000)
        elif interval == '1h':
            limit = min(int(time_diff.total_seconds() / 3600), 1000)
        elif interval == '1d':
            limit = min(time_diff.days, 1000)
        else:
            limit = 1000
        
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
            "startTime": int(start_time.timestamp() * 1000),
            "endTime": int(end_time.timestamp() * 1000),
        }
        
        try:
            response = requests.get(self.klines_url, params=params, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
            
            # 转换为DataFrame
            df = self._parse_klines_data(data)
            return df
            
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"获取历史数据失败: {str(e)}")
    
    def get_current_price(self, symbol: str) -> float:
        """
        获取当前价格
        
        Args:
            symbol: 交易对符号
            
        Returns:
            当前价格
        """
        if not self.is_connected:
            raise ConnectionError("数据源未连接")
        
        params = {"symbol": symbol}
        
        try:
            response = requests.get(self.ticker_url, params=params, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
            return float(data['price'])
            
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"获取当前价格失败: {str(e)}")
    
    def get_available_symbols(self) -> List[str]:
        """
        获取可用的交易对列表
        
        Returns:
            交易对列表
        """
        if not self.is_connected:
            return []
        
        try:
            response = requests.get(self.exchange_info_url, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
            
            symbols = []
            for symbol_info in data['symbols']:
                if (symbol_info['status'] == 'TRADING' and 
                    symbol_info['symbol'].endswith('USDT')):
                    symbols.append(symbol_info['symbol'])
            
            return sorted(symbols)
            
        except requests.exceptions.RequestException:
            return []
    
    def get_supported_intervals(self) -> List[str]:
        """
        获取支持的时间间隔
        
        Returns:
            时间间隔列表
        """
        return ['1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '8h', '12h', '1d', '3d', '1w', '1M']
    
    def _parse_klines_data(self, klines_data: List[List]) -> pd.DataFrame:
        """
        解析K线数据
        
        Args:
            klines_data: 原始K线数据
            
        Returns:
            解析后的DataFrame
        """
        if not klines_data:
            return pd.DataFrame()
        
        # 解析K线数据
        data = []
        for k in klines_data:
            data.append({
                'timestamp': datetime.fromtimestamp(k[0] / 1000),
                'open': float(k[1]),
                'high': float(k[2]),
                'low': float(k[3]),
                'close': float(k[4]),
                'volume': float(k[5]),
                'close_time': datetime.fromtimestamp(k[6] / 1000),
                'quote_volume': float(k[7]),
                'trades': int(k[8]),
                'taker_buy_base_volume': float(k[9]),
                'taker_buy_quote_volume': float(k[10]),
            })
        
        df = pd.DataFrame(data)
        df.set_index('timestamp', inplace=True)
        return df
    
    def get_dca_investment_dates(self, symbol: str, start_date: datetime, 
                                end_date: datetime, invest_day: int) -> List[Dict[str, Any]]:
        """
        获取定投日期的价格数据
        
        Args:
            symbol: 交易对符号
            start_date: 开始日期
            end_date: 结束日期
            invest_day: 定投日期（每月几号）
            
        Returns:
            定投日期数据列表
        """
        # 获取足够的历史数据
        days_diff = (end_date - start_date).days
        limit = min(days_diff + 50, 1000)
        
        params = {
            "symbol": symbol,
            "interval": "1d",
            "limit": limit
        }
        
        try:
            response = requests.get(self.klines_url, params=params, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
            
            # 筛选定投日期
            investment_data = []
            current_month = None
            
            for k in data:
                open_time = datetime.fromtimestamp(k[0] / 1000)
                close_price = float(k[4])
                
                # 如果是新的月份，记录当前月份
                if current_month != open_time.month:
                    current_month = open_time.month
                
                # 如果是定投日期，添加到投资数据中
                if open_time.day == invest_day:
                    investment_data.append({
                        'date': open_time.strftime("%Y-%m-%d"),
                        'datetime': open_time,
                        'close': close_price
                    })
            
            return investment_data
            
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"获取定投数据失败: {str(e)}")
