"""
K线形态识别模块
包含各种经典K线形态的识别功能
"""

import pandas as pd
import numpy as np
from typing import List, Tuple, Dict, Any
import talib


class CandlestickPatterns:
    """K线形态识别类"""
    
    def __init__(self, data: pd.DataFrame):
        """
        初始化K线形态识别器
        
        Args:
            data: 包含OHLCV数据的DataFrame
        """
        self.data = data.copy()
        self._validate_data()
    
    def _validate_data(self) -> None:
        """验证数据格式"""
        required_columns = ['open', 'high', 'low', 'close']
        for col in required_columns:
            if col not in self.data.columns:
                raise ValueError(f"数据中缺少必需的列: {col}")
    
    def hammer(self, threshold: float = 0.6) -> pd.Series:
        """
        识别锤子线形态
        
        Args:
            threshold: 下影线长度阈值（相对于实体长度）
            
        Returns:
            布尔序列，True表示锤子线
        """
        body_size = abs(self.data['close'] - self.data['open'])
        lower_shadow = self.data[['open', 'close']].min(axis=1) - self.data['low']
        upper_shadow = self.data['high'] - self.data[['open', 'close']].max(axis=1)
        
        # 锤子线条件：下影线长，上影线短，实体小
        is_hammer = (
            (lower_shadow > body_size * threshold) &  # 下影线长
            (upper_shadow < body_size * 0.3) &         # 上影线短
            (body_size > 0) &                          # 有实体
            (self.data['close'] > self.data['open'])   # 阳线
        )
        
        return is_hammer
    
    def hanging_man(self, threshold: float = 0.6) -> pd.Series:
        """
        识别上吊线形态
        
        Args:
            threshold: 下影线长度阈值
            
        Returns:
            布尔序列，True表示上吊线
        """
        body_size = abs(self.data['close'] - self.data['open'])
        lower_shadow = self.data[['open', 'close']].min(axis=1) - self.data['low']
        upper_shadow = self.data['high'] - self.data[['open', 'close']].max(axis=1)
        
        # 上吊线条件：下影线长，上影线短，实体小
        is_hanging_man = (
            (lower_shadow > body_size * threshold) &  # 下影线长
            (upper_shadow < body_size * 0.3) &       # 上影线短
            (body_size > 0) &                        # 有实体
            (self.data['close'] < self.data['open']) # 阴线
        )
        
        return is_hanging_man
    
    def doji(self, threshold: float = 0.1) -> pd.Series:
        """
        识别十字星形态
        
        Args:
            threshold: 实体大小阈值（相对于总长度）
            
        Returns:
            布尔序列，True表示十字星
        """
        body_size = abs(self.data['close'] - self.data['open'])
        total_range = self.data['high'] - self.data['low']
        
        # 十字星条件：实体很小
        is_doji = body_size < total_range * threshold
        
        return is_doji
    
    def engulfing_bullish(self) -> pd.Series:
        """
        识别看涨吞没形态
        
        Returns:
            布尔序列，True表示看涨吞没
        """
        prev_open = self.data['open'].shift(1)
        prev_close = self.data['close'].shift(1)
        
        # 看涨吞没条件：
        # 1. 前一根是阴线
        # 2. 当前是阳线
        # 3. 当前开盘价低于前一根收盘价
        # 4. 当前收盘价高于前一根开盘价
        is_bullish_engulfing = (
            (prev_close < prev_open) &                    # 前一根是阴线
            (self.data['close'] > self.data['open']) &    # 当前是阳线
            (self.data['open'] < prev_close) &            # 当前开盘价低于前一根收盘价
            (self.data['close'] > prev_open)              # 当前收盘价高于前一根开盘价
        )
        
        return is_bullish_engulfing
    
    def engulfing_bearish(self) -> pd.Series:
        """
        识别看跌吞没形态
        
        Returns:
            布尔序列，True表示看跌吞没
        """
        prev_open = self.data['open'].shift(1)
        prev_close = self.data['close'].shift(1)
        
        # 看跌吞没条件：
        # 1. 前一根是阳线
        # 2. 当前是阴线
        # 3. 当前开盘价高于前一根收盘价
        # 4. 当前收盘价低于前一根开盘价
        is_bearish_engulfing = (
            (prev_close > prev_open) &                    # 前一根是阳线
            (self.data['close'] < self.data['open']) &    # 当前是阴线
            (self.data['open'] > prev_close) &            # 当前开盘价高于前一根收盘价
            (self.data['close'] < prev_open)              # 当前收盘价低于前一根开盘价
        )
        
        return is_bearish_engulfing
    
    def morning_star(self) -> pd.Series:
        """
        识别启明星形态（三根K线组合）
        
        Returns:
            布尔序列，True表示启明星
        """
        # 第一根：阴线
        first_bearish = (
            (self.data['close'].shift(2) < self.data['open'].shift(2)) &
            (abs(self.data['close'].shift(2) - self.data['open'].shift(2)) > 
             (self.data['high'].shift(2) - self.data['low'].shift(2)) * 0.3)
        )
        
        # 第二根：十字星或小实体
        second_doji = (
            (abs(self.data['close'].shift(1) - self.data['open'].shift(1)) < 
             (self.data['high'].shift(1) - self.data['low'].shift(1)) * 0.3)
        )
        
        # 第三根：阳线，收盘价高于第一根实体中点
        third_bullish = (
            (self.data['close'] > self.data['open']) &
            (self.data['close'] > (self.data['open'].shift(2) + self.data['close'].shift(2)) / 2)
        )
        
        is_morning_star = first_bearish & second_doji & third_bullish
        return is_morning_star
    
    def evening_star(self) -> pd.Series:
        """
        识别黄昏星形态（三根K线组合）
        
        Returns:
            布尔序列，True表示黄昏星
        """
        # 第一根：阳线
        first_bullish = (
            (self.data['close'].shift(2) > self.data['open'].shift(2)) &
            (abs(self.data['close'].shift(2) - self.data['open'].shift(2)) > 
             (self.data['high'].shift(2) - self.data['low'].shift(2)) * 0.3)
        )
        
        # 第二根：十字星或小实体
        second_doji = (
            (abs(self.data['close'].shift(1) - self.data['open'].shift(1)) < 
             (self.data['high'].shift(1) - self.data['low'].shift(1)) * 0.3)
        )
        
        # 第三根：阴线，收盘价低于第一根实体中点
        third_bearish = (
            (self.data['close'] < self.data['open']) &
            (self.data['close'] < (self.data['open'].shift(2) + self.data['close'].shift(2)) / 2)
        )
        
        is_evening_star = first_bullish & second_doji & third_bearish
        return is_evening_star
    
    def three_white_soldiers(self) -> pd.Series:
        """
        识别红三兵形态
        
        Returns:
            布尔序列，True表示红三兵
        """
        # 连续三根阳线
        three_bullish = (
            (self.data['close'].shift(2) > self.data['open'].shift(2)) &
            (self.data['close'].shift(1) > self.data['open'].shift(1)) &
            (self.data['close'] > self.data['open'])
        )
        
        # 每根收盘价都高于前一根
        ascending_closes = (
            (self.data['close'].shift(1) > self.data['close'].shift(2)) &
            (self.data['close'] > self.data['close'].shift(1))
        )
        
        # 每根开盘价都在前一根实体范围内
        opens_in_range = (
            (self.data['open'].shift(1) > self.data['open'].shift(2)) &
            (self.data['open'].shift(1) < self.data['close'].shift(2)) &
            (self.data['open'] > self.data['open'].shift(1)) &
            (self.data['open'] < self.data['close'].shift(1))
        )
        
        is_three_white_soldiers = three_bullish & ascending_closes & opens_in_range
        return is_three_white_soldiers
    
    def three_black_crows(self) -> pd.Series:
        """
        识别三只乌鸦形态
        
        Returns:
            布尔序列，True表示三只乌鸦
        """
        # 连续三根阴线
        three_bearish = (
            (self.data['close'].shift(2) < self.data['open'].shift(2)) &
            (self.data['close'].shift(1) < self.data['open'].shift(1)) &
            (self.data['close'] < self.data['open'])
        )
        
        # 每根收盘价都低于前一根
        descending_closes = (
            (self.data['close'].shift(1) < self.data['close'].shift(2)) &
            (self.data['close'] < self.data['close'].shift(1))
        )
        
        # 每根开盘价都在前一根实体范围内
        opens_in_range = (
            (self.data['open'].shift(1) < self.data['open'].shift(2)) &
            (self.data['open'].shift(1) > self.data['close'].shift(2)) &
            (self.data['open'] < self.data['open'].shift(1)) &
            (self.data['open'] > self.data['close'].shift(1))
        )
        
        is_three_black_crows = three_bearish & descending_closes & opens_in_range
        return is_three_black_crows
    
    def get_all_patterns(self) -> Dict[str, pd.Series]:
        """
        识别所有K线形态
        
        Returns:
            包含所有形态的字典
        """
        patterns = {}
        
        # 单根K线形态
        patterns['hammer'] = self.hammer()
        patterns['hanging_man'] = self.hanging_man()
        patterns['doji'] = self.doji()
        
        # 两根K线形态
        patterns['bullish_engulfing'] = self.engulfing_bullish()
        patterns['bearish_engulfing'] = self.engulfing_bearish()
        
        # 三根K线形态
        patterns['morning_star'] = self.morning_star()
        patterns['evening_star'] = self.evening_star()
        patterns['three_white_soldiers'] = self.three_white_soldiers()
        patterns['three_black_crows'] = self.three_black_crows()
        
        return patterns
    
    def get_bullish_patterns(self) -> pd.Series:
        """
        获取所有看涨形态的综合信号
        
        Returns:
            布尔序列，True表示出现看涨形态
        """
        bullish_patterns = [
            self.hammer(),
            self.engulfing_bullish(),
            self.morning_star(),
            self.three_white_soldiers()
        ]
        
        # 任一看涨形态出现即为True
        combined = pd.Series(False, index=self.data.index)
        for pattern in bullish_patterns:
            combined = combined | pattern
        
        return combined
    
    def get_bearish_patterns(self) -> pd.Series:
        """
        获取所有看跌形态的综合信号
        
        Returns:
            布尔序列，True表示出现看跌形态
        """
        bearish_patterns = [
            self.hanging_man(),
            self.engulfing_bearish(),
            self.evening_star(),
            self.three_black_crows()
        ]
        
        # 任一看跌形态出现即为True
        combined = pd.Series(False, index=self.data.index)
        for pattern in bearish_patterns:
            combined = combined | pattern
        
        return combined
