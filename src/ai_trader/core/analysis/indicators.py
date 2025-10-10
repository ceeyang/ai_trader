"""
技术指标计算模块
包含移动平均线、MACD、RSI、KDJ等常用技术指标
"""

import pandas as pd
import numpy as np
from typing import Tuple, Optional, Dict, Any
import talib


class TechnicalIndicators:
    """技术指标计算类"""
    
    def __init__(self, data: pd.DataFrame):
        """
        初始化技术指标计算器
        
        Args:
            data: 包含OHLCV数据的DataFrame，必须包含'open', 'high', 'low', 'close', 'volume'列
        """
        self.data = data.copy()
        self._validate_data()
    
    def _validate_data(self) -> None:
        """验证数据格式"""
        required_columns = ['open', 'high', 'low', 'close', 'volume']
        for col in required_columns:
            if col not in self.data.columns:
                raise ValueError(f"数据中缺少必需的列: {col}")
    
    def sma(self, period: int = 20) -> pd.Series:
        """
        计算简单移动平均线
        
        Args:
            period: 计算周期
            
        Returns:
            移动平均线序列
        """
        return self.data['close'].rolling(window=period).mean()
    
    def ema(self, period: int = 20) -> pd.Series:
        """
        计算指数移动平均线
        
        Args:
            period: 计算周期
            
        Returns:
            指数移动平均线序列
        """
        return self.data['close'].ewm(span=period).mean()
    
    def macd(self, fast_period: int = 12, slow_period: int = 26, signal_period: int = 9) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """
        计算MACD指标
        
        Args:
            fast_period: 快线周期
            slow_period: 慢线周期
            signal_period: 信号线周期
            
        Returns:
            (DIF, DEA, MACD柱状图)
        """
        dif = self.ema(fast_period) - self.ema(slow_period)
        dea = dif.ewm(span=signal_period).mean()
        macd_hist = (dif - dea) * 2
        return dif, dea, macd_hist
    
    def rsi(self, period: int = 14) -> pd.Series:
        """
        计算RSI相对强弱指数
        
        Args:
            period: 计算周期
            
        Returns:
            RSI序列
        """
        rsi_values = talib.RSI(self.data['close'].values, timeperiod=period)
        return pd.Series(rsi_values, index=self.data.index)
    
    def kdj(self, k_period: int = 9, d_period: int = 3, j_period: int = 3) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """
        计算KDJ指标
        
        Args:
            k_period: K值周期
            d_period: D值周期
            j_period: J值周期
            
        Returns:
            (K值, D值, J值)
        """
        # 计算RSV
        low_min = self.data['low'].rolling(window=k_period).min()
        high_max = self.data['high'].rolling(window=k_period).max()
        rsv = (self.data['close'] - low_min) / (high_max - low_min) * 100
        
        # 计算K、D、J值
        k = rsv.ewm(alpha=1/d_period).mean()
        d = k.ewm(alpha=1/j_period).mean()
        j = 3 * k - 2 * d
        
        return k, d, j
    
    def bollinger_bands(self, period: int = 20, std_dev: float = 2) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """
        计算布林带
        
        Args:
            period: 计算周期
            std_dev: 标准差倍数
            
        Returns:
            (上轨, 中轨, 下轨)
        """
        sma = self.sma(period)
        std = self.data['close'].rolling(window=period).std()
        
        upper_band = sma + (std * std_dev)
        lower_band = sma - (std * std_dev)
        
        return upper_band, sma, lower_band
    
    def obv(self) -> pd.Series:
        """
        计算能量潮指标OBV
        
        Returns:
            OBV序列
        """
        obv_values = talib.OBV(self.data['close'].values, self.data['volume'].values)
        return pd.Series(obv_values, index=self.data.index)
    
    def atr(self, period: int = 14) -> pd.Series:
        """
        计算平均真实波幅ATR
        
        Args:
            period: 计算周期
            
        Returns:
            ATR序列
        """
        atr_values = talib.ATR(self.data['high'].values, self.data['low'].values, 
                              self.data['close'].values, timeperiod=period)
        return pd.Series(atr_values, index=self.data.index)
    
    def williams_r(self, period: int = 14) -> pd.Series:
        """
        计算威廉指标
        
        Args:
            period: 计算周期
            
        Returns:
            威廉指标序列
        """
        willr_values = talib.WILLR(self.data['high'].values, self.data['low'].values, 
                                  self.data['close'].values, timeperiod=period)
        return pd.Series(willr_values, index=self.data.index)
    
    def stochastic(self, k_period: int = 14, d_period: int = 3) -> Tuple[pd.Series, pd.Series]:
        """
        计算随机指标
        
        Args:
            k_period: K值周期
            d_period: D值周期
            
        Returns:
            (K值, D值)
        """
        k_values, d_values = talib.STOCH(self.data['high'].values, self.data['low'].values, 
                                        self.data['close'].values, 
                                        fastk_period=k_period, slowk_period=d_period, 
                                        slowd_period=d_period)
        return pd.Series(k_values, index=self.data.index), pd.Series(d_values, index=self.data.index)
    
    def get_all_indicators(self) -> Dict[str, Any]:
        """
        计算所有技术指标
        
        Returns:
            包含所有指标的字典
        """
        indicators = {}
        
        # 移动平均线
        indicators['sma_5'] = self.sma(5)
        indicators['sma_10'] = self.sma(10)
        indicators['sma_20'] = self.sma(20)
        indicators['sma_50'] = self.sma(50)
        indicators['sma_200'] = self.sma(200)
        
        # 指数移动平均线
        indicators['ema_12'] = self.ema(12)
        indicators['ema_26'] = self.ema(26)
        
        # MACD
        dif, dea, macd_hist = self.macd()
        indicators['macd_dif'] = dif
        indicators['macd_dea'] = dea
        indicators['macd_hist'] = macd_hist
        
        # RSI
        indicators['rsi'] = self.rsi()
        
        # KDJ
        k, d, j = self.kdj()
        indicators['kdj_k'] = k
        indicators['kdj_d'] = d
        indicators['kdj_j'] = j
        
        # 布林带
        bb_upper, bb_middle, bb_lower = self.bollinger_bands()
        indicators['bb_upper'] = bb_upper
        indicators['bb_middle'] = bb_middle
        indicators['bb_lower'] = bb_lower
        
        # 其他指标
        indicators['obv'] = self.obv()
        indicators['atr'] = self.atr()
        indicators['williams_r'] = self.williams_r()
        
        # 随机指标
        stoch_k, stoch_d = self.stochastic()
        indicators['stoch_k'] = stoch_k
        indicators['stoch_d'] = stoch_d
        
        return indicators
