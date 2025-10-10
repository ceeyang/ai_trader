"""
交易信号检测模块
结合技术指标和K线形态生成入场和出场信号
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional, Any
from .indicators import TechnicalIndicators
from .patterns import CandlestickPatterns


class SignalDetector:
    """交易信号检测器"""
    
    def __init__(self, data: pd.DataFrame):
        """
        初始化信号检测器
        
        Args:
            data: 包含OHLCV数据的DataFrame
        """
        self.data = data.copy()
        self.indicators = TechnicalIndicators(data)
        self.patterns = CandlestickPatterns(data)
        
        # 计算所有指标和形态
        self.indicator_data = self.indicators.get_all_indicators()
        self.pattern_data = self.patterns.get_all_patterns()
    
    def get_trend_direction(self, short_period: int = 20, long_period: int = 50) -> pd.Series:
        """
        判断趋势方向
        
        Args:
            short_period: 短期均线周期
            long_period: 长期均线周期
            
        Returns:
            趋势方向：1为上涨，-1为下跌，0为震荡
        """
        sma_short = self.indicators.sma(short_period)
        sma_long = self.indicators.sma(long_period)
        
        # 价格在均线上方且短期均线在长期均线上方为上涨趋势
        uptrend = (self.data['close'] > sma_short) & (sma_short > sma_long)
        # 价格在均线下方且短期均线在长期均线下方为下跌趋势
        downtrend = (self.data['close'] < sma_short) & (sma_short < sma_long)
        
        trend = pd.Series(0, index=self.data.index)
        trend[uptrend] = 1
        trend[downtrend] = -1
        
        return trend
    
    def get_macd_signals(self) -> Tuple[pd.Series, pd.Series]:
        """
        获取MACD信号
        
        Returns:
            (入场信号, 出场信号)
        """
        dif, dea, macd_hist = self.indicators.macd()
        
        # 入场信号：DIF上穿DEA且MACD柱状图由负转正
        macd_bullish = (dif > dea) & (dif.shift(1) <= dea.shift(1)) & (macd_hist > 0)
        
        # 出场信号：DIF下穿DEA或MACD柱状图由正转负
        macd_bearish = (dif < dea) & (dif.shift(1) >= dea.shift(1)) | (macd_hist < 0) & (macd_hist.shift(1) >= 0)
        
        return macd_bullish, macd_bearish
    
    def get_rsi_signals(self, oversold: float = 30, overbought: float = 70) -> Tuple[pd.Series, pd.Series]:
        """
        获取RSI信号
        
        Args:
            oversold: 超卖阈值
            overbought: 超买阈值
            
        Returns:
            (入场信号, 出场信号)
        """
        rsi = self.indicator_data['rsi']
        
        # 入场信号：RSI从超卖区域向上突破
        rsi_bullish = (rsi > oversold) & (rsi.shift(1) <= oversold)
        
        # 出场信号：RSI进入超买区域或从超买区域向下
        rsi_bearish = (rsi > overbought) | ((rsi < overbought) & (rsi.shift(1) >= overbought))
        
        return rsi_bullish, rsi_bearish
    
    def get_kdj_signals(self) -> Tuple[pd.Series, pd.Series]:
        """
        获取KDJ信号
        
        Returns:
            (入场信号, 出场信号)
        """
        k = self.indicator_data['kdj_k']
        d = self.indicator_data['kdj_d']
        j = self.indicator_data['kdj_j']
        
        # 入场信号：K线上穿D线且J值从低位向上
        kdj_bullish = (k > d) & (k.shift(1) <= d.shift(1)) & (j > 20)
        
        # 出场信号：K线下穿D线或J值进入超买区域
        kdj_bearish = (k < d) & (k.shift(1) >= d.shift(1)) | (j > 80)
        
        return kdj_bullish, kdj_bearish
    
    def get_bollinger_signals(self) -> Tuple[pd.Series, pd.Series]:
        """
        获取布林带信号
        
        Returns:
            (入场信号, 出场信号)
        """
        bb_upper = self.indicator_data['bb_upper']
        bb_lower = self.indicator_data['bb_lower']
        bb_middle = self.indicator_data['bb_middle']
        
        # 入场信号：价格触及下轨后反弹
        bb_bullish = (self.data['close'] <= bb_lower) & (self.data['close'].shift(1) > bb_lower.shift(1))
        
        # 出场信号：价格触及上轨后回落
        bb_bearish = (self.data['close'] >= bb_upper) & (self.data['close'].shift(1) < bb_upper.shift(1))
        
        return bb_bullish, bb_bearish
    
    def get_volume_confirmation(self, period: int = 20) -> pd.Series:
        """
        获取成交量确认信号
        
        Args:
            period: 成交量均线周期
            
        Returns:
            成交量确认信号
        """
        volume_sma = self.data['volume'].rolling(window=period).mean()
        
        # 成交量放大确认
        volume_confirmation = self.data['volume'] > volume_sma * 1.5
        
        return volume_confirmation
    
    def get_support_resistance_levels(self, window: int = 20) -> Tuple[pd.Series, pd.Series]:
        """
        识别支撑位和阻力位
        
        Args:
            window: 计算窗口
            
        Returns:
            (支撑位, 阻力位)
        """
        # 使用滚动窗口计算局部最高点和最低点
        resistance = self.data['high'].rolling(window=window, center=True).max()
        support = self.data['low'].rolling(window=window, center=True).min()
        
        return support, resistance
    
    def get_breakout_signals(self, window: int = 20) -> Tuple[pd.Series, pd.Series]:
        """
        获取突破信号
        
        Args:
            window: 计算窗口
            
        Returns:
            (向上突破信号, 向下突破信号)
        """
        support, resistance = self.get_support_resistance_levels(window)
        
        # 向上突破阻力位
        breakout_up = (self.data['close'] > resistance.shift(1)) & (self.data['close'].shift(1) <= resistance.shift(1))
        
        # 向下突破支撑位
        breakout_down = (self.data['close'] < support.shift(1)) & (self.data['close'].shift(1) >= support.shift(1))
        
        return breakout_up, breakout_down
    
    def get_comprehensive_entry_signals(self) -> pd.Series:
        """
        获取综合入场信号
        
        Returns:
            综合入场信号
        """
        # 获取各种信号
        trend = self.get_trend_direction()
        macd_bullish, _ = self.get_macd_signals()
        rsi_bullish, _ = self.get_rsi_signals()
        kdj_bullish, _ = self.get_kdj_signals()
        bb_bullish, _ = self.get_bollinger_signals()
        breakout_up, _ = self.get_breakout_signals()
        volume_conf = self.get_volume_confirmation()
        bullish_patterns = self.patterns.get_bullish_patterns()
        
        # 综合入场条件（需要满足多个条件）
        entry_signals = (
            (trend == 1) &  # 上涨趋势
            (macd_bullish | rsi_bullish | kdj_bullish) &  # 至少一个指标确认
            (bb_bullish | breakout_up) &  # 布林带或突破信号
            (volume_conf) &  # 成交量确认
            (bullish_patterns)  # K线形态确认
        )
        
        return entry_signals
    
    def get_comprehensive_exit_signals(self) -> pd.Series:
        """
        获取综合出场信号
        
        Returns:
            综合出场信号
        """
        # 获取各种信号
        trend = self.get_trend_direction()
        _, macd_bearish = self.get_macd_signals()
        _, rsi_bearish = self.get_rsi_signals()
        _, kdj_bearish = self.get_kdj_signals()
        _, bb_bearish = self.get_bollinger_signals()
        _, breakout_down = self.get_breakout_signals()
        bearish_patterns = self.patterns.get_bearish_patterns()
        
        # 综合出场条件（满足任一条件即可出场）
        exit_signals = (
            (trend == -1) |  # 趋势转跌
            macd_bearish |  # MACD转弱
            rsi_bearish |   # RSI超买
            kdj_bearish |   # KDJ转弱
            bb_bearish |    # 布林带上轨压力
            breakout_down | # 向下突破
            bearish_patterns  # 看跌形态
        )
        
        return exit_signals
    
    def get_signal_strength(self, signals: pd.Series) -> pd.Series:
        """
        计算信号强度
        
        Args:
            signals: 信号序列
            
        Returns:
            信号强度序列
        """
        strength = pd.Series(0.0, index=signals.index)
        
        # 计算各种指标的权重
        trend_weight = 0.3
        indicator_weight = 0.3
        pattern_weight = 0.2
        volume_weight = 0.2
        
        # 趋势强度
        trend = self.get_trend_direction()
        trend_strength = abs(trend) * trend_weight
        
        # 指标强度
        macd_bullish, _ = self.get_macd_signals()
        rsi_bullish, _ = self.get_rsi_signals()
        kdj_bullish, _ = self.get_kdj_signals()
        indicator_strength = (macd_bullish.astype(int) + rsi_bullish.astype(int) + 
                             kdj_bullish.astype(int)) * indicator_weight / 3
        
        # 形态强度
        bullish_patterns = self.patterns.get_bullish_patterns()
        pattern_strength = bullish_patterns.astype(int) * pattern_weight
        
        # 成交量强度
        volume_conf = self.get_volume_confirmation()
        volume_strength = volume_conf.astype(int) * volume_weight
        
        # 综合强度
        strength = trend_strength + indicator_strength + pattern_strength + volume_strength
        
        return strength
    
    def get_all_signals(self) -> Dict[str, Any]:
        """
        获取所有信号
        
        Returns:
            包含所有信号的字典
        """
        signals = {}
        
        # 基础信号
        signals['trend'] = self.get_trend_direction()
        signals['entry'] = self.get_comprehensive_entry_signals()
        signals['exit'] = self.get_comprehensive_exit_signals()
        signals['signal_strength'] = self.get_signal_strength(signals['entry'])
        
        # 详细信号
        macd_bullish, macd_bearish = self.get_macd_signals()
        rsi_bullish, rsi_bearish = self.get_rsi_signals()
        kdj_bullish, kdj_bearish = self.get_kdj_signals()
        bb_bullish, bb_bearish = self.get_bollinger_signals()
        breakout_up, breakout_down = self.get_breakout_signals()
        
        signals['macd_bullish'] = macd_bullish
        signals['macd_bearish'] = macd_bearish
        signals['rsi_bullish'] = rsi_bullish
        signals['rsi_bearish'] = rsi_bearish
        signals['kdj_bullish'] = kdj_bullish
        signals['kdj_bearish'] = kdj_bearish
        signals['bb_bullish'] = bb_bullish
        signals['bb_bearish'] = bb_bearish
        signals['breakout_up'] = breakout_up
        signals['breakout_down'] = breakout_down
        
        # 形态信号
        signals['bullish_patterns'] = self.patterns.get_bullish_patterns()
        signals['bearish_patterns'] = self.patterns.get_bearish_patterns()
        
        # 成交量信号
        signals['volume_confirmation'] = self.get_volume_confirmation()
        
        return signals
    
    def find_signal_points(self) -> Tuple[List[int], List[int]]:
        """
        找到所有入场和出场点
        
        Returns:
            (入场点索引列表, 出场点索引列表)
        """
        entry_signals = self.get_comprehensive_entry_signals()
        exit_signals = self.get_comprehensive_exit_signals()
        
        # 找到信号点
        entry_points = entry_signals[entry_signals].index.tolist()
        exit_points = exit_signals[exit_signals].index.tolist()
        
        return entry_points, exit_points
