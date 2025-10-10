"""
图表绘制模块
提供K线图、技术指标和交易信号的图表显示功能
"""

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Rectangle
import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional, Any
from datetime import datetime
import warnings

# 设置中文字体支持
plt.rcParams['font.sans-serif'] = ['SimHei', 'Arial Unicode MS', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

# 忽略matplotlib警告
warnings.filterwarnings('ignore', category=UserWarning)


class ChartRenderer:
    """图表渲染器"""
    
    def __init__(self, figsize: Tuple[int, int] = (12, 8)):
        """
        初始化图表渲染器
        
        Args:
            figsize: 图表尺寸
        """
        self.figsize = figsize
        self.fig: Optional[plt.Figure] = None
        self.ax: Optional[plt.Axes] = None
        
    def create_candlestick_chart(self, data: pd.DataFrame, 
                                entry_signals: Optional[pd.Series] = None,
                                exit_signals: Optional[pd.Series] = None,
                                indicators: Optional[Dict[str, pd.Series]] = None,
                                title: str = "K线图与交易信号") -> plt.Figure:
        """
        创建K线图
        
        Args:
            data: OHLCV数据
            entry_signals: 入场信号
            exit_signals: 出场信号
            indicators: 技术指标数据
            title: 图表标题
            
        Returns:
            matplotlib图表对象
        """
        # 创建图表
        self.fig, self.ax = plt.subplots(figsize=self.figsize)
        
        # 绘制K线图
        self._plot_candlesticks(data)
        
        # 绘制技术指标
        if indicators:
            self._plot_indicators(data, indicators)
        
        # 绘制交易信号
        if entry_signals is not None:
            self._plot_entry_signals(data, entry_signals)
        
        if exit_signals is not None:
            self._plot_exit_signals(data, exit_signals)
        
        # 设置图表样式
        self._configure_chart(data, title)
        
        return self.fig
    
    def _plot_candlesticks(self, data: pd.DataFrame) -> None:
        """绘制K线图"""
        # 计算K线颜色
        colors = ['red' if close >= open_price else 'green' 
                 for close, open_price in zip(data['close'], data['open'])]
        
        # 绘制K线实体
        for i, (date, row) in enumerate(data.iterrows()):
            open_price = row['open']
            close = row['close']
            high = row['high']
            low = row['low']
            
            # 确定颜色
            color = 'red' if close >= open_price else 'green'
            
            # 绘制上下影线
            self.ax.plot([i, i], [low, high], color='black', linewidth=0.8)
            
            # 绘制实体
            body_height = abs(close - open_price)
            body_bottom = min(open_price, close)
            
            if body_height > 0:
                rect = Rectangle((i - 0.3, body_bottom), 0.6, body_height, 
                               facecolor=color, edgecolor='black', linewidth=0.5)
                self.ax.add_patch(rect)
            else:
                # 十字星
                self.ax.plot([i - 0.3, i + 0.3], [open_price, open_price], 
                           color='black', linewidth=1)
    
    def _plot_indicators(self, data: pd.DataFrame, indicators: Dict[str, pd.Series]) -> None:
        """绘制技术指标"""
        x = range(len(data))
        
        # 绘制移动平均线
        if 'sma_20' in indicators:
            self.ax.plot(x, indicators['sma_20'], label='SMA20', color='blue', linewidth=1)
        if 'sma_50' in indicators:
            self.ax.plot(x, indicators['sma_50'], label='SMA50', color='orange', linewidth=1)
        
        # 绘制布林带
        if all(key in indicators for key in ['bb_upper', 'bb_middle', 'bb_lower']):
            self.ax.plot(x, indicators['bb_upper'], label='布林带上轨', color='purple', alpha=0.7, linewidth=1)
            self.ax.plot(x, indicators['bb_middle'], label='布林带中轨', color='purple', alpha=0.7, linewidth=1)
            self.ax.plot(x, indicators['bb_lower'], label='布林带下轨', color='purple', alpha=0.7, linewidth=1)
            # 填充布林带区域
            self.ax.fill_between(x, indicators['bb_upper'], indicators['bb_lower'], 
                               alpha=0.1, color='purple')
    
    def _plot_entry_signals(self, data: pd.DataFrame, entry_signals: pd.Series) -> None:
        """绘制入场信号"""
        entry_points = data[entry_signals]
        if not entry_points.empty:
            x_positions = [i for i, signal in enumerate(entry_signals) if signal]
            y_positions = [data.iloc[i]['low'] * 0.98 for i in x_positions]  # 在K线下方显示
            
            self.ax.scatter(x_positions, y_positions, 
                          color='green', marker='^', s=100, 
                          label='入场信号', zorder=5)
            
            # 添加信号标注
            for i, (date, row) in enumerate(entry_points.iterrows()):
                if i < 10:  # 只标注前10个信号，避免图表过于拥挤
                    self.ax.annotate(f'入场\n{date.strftime("%m-%d")}', 
                                   xy=(data.index.get_loc(date), row['low'] * 0.95),
                                   xytext=(10, 20), textcoords='offset points',
                                   bbox=dict(boxstyle='round,pad=0.3', facecolor='lightgreen', alpha=0.7),
                                   arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=0'),
                                   fontsize=8, ha='center')
    
    def _plot_exit_signals(self, data: pd.DataFrame, exit_signals: pd.Series) -> None:
        """绘制出场信号"""
        exit_points = data[exit_signals]
        if not exit_points.empty:
            x_positions = [i for i, signal in enumerate(exit_signals) if signal]
            y_positions = [data.iloc[i]['high'] * 1.02 for i in x_positions]  # 在K线上方显示
            
            self.ax.scatter(x_positions, y_positions, 
                          color='red', marker='v', s=100, 
                          label='出场信号', zorder=5)
            
            # 添加信号标注
            for i, (date, row) in enumerate(exit_points.iterrows()):
                if i < 10:  # 只标注前10个信号
                    self.ax.annotate(f'出场\n{date.strftime("%m-%d")}', 
                                   xy=(data.index.get_loc(date), row['high'] * 1.05),
                                   xytext=(10, -30), textcoords='offset points',
                                   bbox=dict(boxstyle='round,pad=0.3', facecolor='lightcoral', alpha=0.7),
                                   arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=0'),
                                   fontsize=8, ha='center')
    
    def _configure_chart(self, data: pd.DataFrame, title: str) -> None:
        """配置图表样式"""
        # 设置标题
        self.ax.set_title(title, fontsize=14, fontweight='bold', pad=20)
        
        # 设置坐标轴标签
        self.ax.set_xlabel('时间', fontsize=12)
        self.ax.set_ylabel('价格', fontsize=12)
        
        # 设置x轴刻度
        step = max(1, len(data) // 10)  # 显示约10个时间点
        x_ticks = range(0, len(data), step)
        x_labels = [data.index[i].strftime('%Y-%m-%d') for i in x_ticks]
        self.ax.set_xticks(x_ticks)
        self.ax.set_xticklabels(x_labels, rotation=45, ha='right')
        
        # 设置网格
        self.ax.grid(True, alpha=0.3, linestyle='--')
        
        # 设置图例
        self.ax.legend(loc='upper left', fontsize=10)
        
        # 调整布局
        plt.tight_layout()
    
    def create_technical_indicators_chart(self, data: pd.DataFrame, 
                                        indicators: Dict[str, pd.Series],
                                        title: str = "技术指标图") -> plt.Figure:
        """
        创建技术指标图表
        
        Args:
            data: OHLCV数据
            indicators: 技术指标数据
            title: 图表标题
            
        Returns:
            matplotlib图表对象
        """
        # 创建子图
        fig, axes = plt.subplots(3, 1, figsize=(12, 10), sharex=True)
        fig.suptitle(title, fontsize=16, fontweight='bold')
        
        x = range(len(data))
        
        # 主图：价格和移动平均线
        ax1 = axes[0]
        ax1.plot(x, data['close'], label='收盘价', color='black', linewidth=1)
        
        if 'sma_20' in indicators:
            ax1.plot(x, indicators['sma_20'], label='SMA20', color='blue', linewidth=1)
        if 'sma_50' in indicators:
            ax1.plot(x, indicators['sma_50'], label='SMA50', color='orange', linewidth=1)
        
        ax1.set_ylabel('价格')
        ax1.legend()
        ax1.grid(True, alpha=0.3)
        
        # MACD图
        ax2 = axes[1]
        if all(key in indicators for key in ['macd_dif', 'macd_dea', 'macd_hist']):
            ax2.plot(x, indicators['macd_dif'], label='DIF', color='blue', linewidth=1)
            ax2.plot(x, indicators['macd_dea'], label='DEA', color='red', linewidth=1)
            ax2.bar(x, indicators['macd_hist'], label='MACD', alpha=0.6, width=0.8)
            ax2.axhline(y=0, color='black', linestyle='-', alpha=0.3)
        
        ax2.set_ylabel('MACD')
        ax2.legend()
        ax2.grid(True, alpha=0.3)
        
        # RSI图
        ax3 = axes[2]
        if 'rsi' in indicators:
            ax3.plot(x, indicators['rsi'], label='RSI', color='purple', linewidth=1)
            ax3.axhline(y=70, color='red', linestyle='--', alpha=0.7, label='超买线')
            ax3.axhline(y=30, color='green', linestyle='--', alpha=0.7, label='超卖线')
            ax3.axhline(y=50, color='black', linestyle='-', alpha=0.3)
        
        ax3.set_ylabel('RSI')
        ax3.set_xlabel('时间')
        ax3.legend()
        ax3.grid(True, alpha=0.3)
        ax3.set_ylim(0, 100)
        
        # 设置x轴刻度
        step = max(1, len(data) // 10)
        x_ticks = range(0, len(data), step)
        x_labels = [data.index[i].strftime('%Y-%m-%d') for i in x_ticks]
        ax3.set_xticks(x_ticks)
        ax3.set_xticklabels(x_labels, rotation=45, ha='right')
        
        plt.tight_layout()
        return fig
    
    def save_chart(self, filename: str, dpi: int = 300) -> None:
        """
        保存图表到文件
        
        Args:
            filename: 文件名
            dpi: 图片分辨率
        """
        if self.fig is not None:
            self.fig.savefig(filename, dpi=dpi, bbox_inches='tight')
            plt.close(self.fig)
    
    def show_chart(self) -> None:
        """显示图表"""
        if self.fig is not None:
            plt.show()


class TradingChart:
    """交易图表类，整合K线图和技术指标"""
    
    def __init__(self, data: pd.DataFrame):
        """
        初始化交易图表
        
        Args:
            data: OHLCV数据
        """
        self.data = data.copy()
        self.renderer = ChartRenderer()
        
    def plot_with_signals(self, entry_signals: pd.Series, 
                         exit_signals: pd.Series,
                         indicators: Optional[Dict[str, pd.Series]] = None,
                         symbol: str = "BTCUSDT") -> plt.Figure:
        """
        绘制带信号的K线图
        
        Args:
            entry_signals: 入场信号
            exit_signals: 出场信号
            indicators: 技术指标
            symbol: 交易对符号
            
        Returns:
            图表对象
        """
        title = f"{symbol} K线图与交易信号"
        return self.renderer.create_candlestick_chart(
            self.data, entry_signals, exit_signals, indicators, title
        )
    
    def plot_indicators_only(self, indicators: Dict[str, pd.Series], 
                            symbol: str = "BTCUSDT") -> plt.Figure:
        """
        绘制技术指标图
        
        Args:
            indicators: 技术指标数据
            symbol: 交易对符号
            
        Returns:
            图表对象
        """
        title = f"{symbol} 技术指标图"
        return self.renderer.create_technical_indicators_chart(
            self.data, indicators, title
        )
    
    def get_signal_statistics(self, entry_signals: pd.Series, 
                             exit_signals: pd.Series) -> Dict[str, Any]:
        """
        获取信号统计信息
        
        Args:
            entry_signals: 入场信号
            exit_signals: 出场信号
            
        Returns:
            统计信息字典
        """
        return {
            'total_entry_signals': int(entry_signals.sum()),
            'total_exit_signals': int(exit_signals.sum()),
            'entry_frequency': float(entry_signals.sum() / len(entry_signals)),
            'exit_frequency': float(exit_signals.sum() / len(exit_signals)),
            'data_period': f"{self.data.index[0].strftime('%Y-%m-%d')} 到 {self.data.index[-1].strftime('%Y-%m-%d')}",
            'total_candles': len(self.data)
        }
