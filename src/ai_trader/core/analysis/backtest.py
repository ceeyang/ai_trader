"""
回测分析模块
用于测试交易策略的历史表现
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass
from .signals import SignalDetector


@dataclass
class Trade:
    """交易记录"""
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    pnl_percent: float
    duration: int  # 持仓天数
    signal_strength: float


@dataclass
class BacktestResult:
    """回测结果"""
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_pnl: float
    total_return: float
    max_drawdown: float
    sharpe_ratio: float
    avg_trade_duration: float
    trades: List[Trade]


class BacktestEngine:
    """回测引擎"""
    
    def __init__(self, data: pd.DataFrame, initial_capital: float = 100000):
        """
        初始化回测引擎
        
        Args:
            data: 历史数据
            initial_capital: 初始资金
        """
        self.data = data.copy()
        self.initial_capital = initial_capital
        self.signal_detector = SignalDetector(data)
        
        # 回测参数
        self.commission_rate = 0.001  # 手续费率
        self.slippage_rate = 0.0005   # 滑点率
        
    def run_backtest(self, 
                    entry_signals: Optional[pd.Series] = None,
                    exit_signals: Optional[pd.Series] = None,
                    position_size: float = 0.1) -> BacktestResult:
        """
        运行回测
        
        Args:
            entry_signals: 入场信号，如果为None则使用默认信号
            exit_signals: 出场信号，如果为None则使用默认信号
            position_size: 每次交易仓位大小（占总资金比例）
            
        Returns:
            回测结果
        """
        if entry_signals is None:
            entry_signals = self.signal_detector.get_comprehensive_entry_signals()
        if exit_signals is None:
            exit_signals = self.signal_detector.get_comprehensive_exit_signals()
        
        # 初始化交易状态
        trades = []
        current_position = None
        capital = self.initial_capital
        
        # 遍历所有数据点
        for i in range(len(self.data)):
            current_time = self.data.index[i]
            current_price = self.data['close'].iloc[i]
            
            # 检查入场信号
            if entry_signals.iloc[i] and current_position is None:
                # 计算交易数量
                trade_amount = capital * position_size
                quantity = trade_amount / current_price
                
                # 考虑手续费和滑点
                actual_price = current_price * (1 + self.slippage_rate)
                actual_quantity = quantity * (1 - self.commission_rate)
                
                current_position = {
                    'entry_time': current_time,
                    'entry_price': actual_price,
                    'quantity': actual_quantity,
                    'entry_capital': trade_amount
                }
            
            # 检查出场信号
            elif exit_signals.iloc[i] and current_position is not None:
                # 计算出场价格
                exit_price = current_price * (1 - self.slippage_rate)
                
                # 计算盈亏
                pnl = (exit_price - current_position['entry_price']) * current_position['quantity']
                pnl_percent = (exit_price - current_position['entry_price']) / current_position['entry_price']
                
                # 计算持仓天数
                duration = (current_time - current_position['entry_time']).days
                
                # 获取信号强度
                signal_strength = self.signal_detector.get_signal_strength(entry_signals).iloc[i] if i < len(self.signal_detector.get_signal_strength(entry_signals)) else 0.5
                
                # 创建交易记录
                trade = Trade(
                    entry_time=current_position['entry_time'],
                    exit_time=current_time,
                    entry_price=current_position['entry_price'],
                    exit_price=exit_price,
                    quantity=current_position['quantity'],
                    pnl=pnl,
                    pnl_percent=pnl_percent,
                    duration=duration,
                    signal_strength=signal_strength
                )
                
                trades.append(trade)
                
                # 更新资金
                capital += pnl
                
                # 清空仓位
                current_position = None
        
        # 计算回测结果
        return self._calculate_results(trades)
    
    def _calculate_results(self, trades: List[Trade]) -> BacktestResult:
        """
        计算回测结果
        
        Args:
            trades: 交易列表
            
        Returns:
            回测结果
        """
        if not trades:
            return BacktestResult(
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                win_rate=0.0,
                total_pnl=0.0,
                total_return=0.0,
                max_drawdown=0.0,
                sharpe_ratio=0.0,
                avg_trade_duration=0.0,
                trades=[]
            )
        
        # 基础统计
        total_trades = len(trades)
        winning_trades = sum(1 for trade in trades if trade.pnl > 0)
        losing_trades = total_trades - winning_trades
        win_rate = winning_trades / total_trades if total_trades > 0 else 0
        
        # 盈亏统计
        total_pnl = sum(trade.pnl for trade in trades)
        total_return = total_pnl / self.initial_capital
        
        # 最大回撤
        cumulative_pnl = np.cumsum([trade.pnl for trade in trades])
        running_max = np.maximum.accumulate(cumulative_pnl)
        drawdown = running_max - cumulative_pnl
        max_drawdown = np.max(drawdown) if len(drawdown) > 0 else 0
        
        # 夏普比率
        if len(trades) > 1:
            returns = [trade.pnl_percent for trade in trades]
            sharpe_ratio = np.mean(returns) / np.std(returns) * np.sqrt(252) if np.std(returns) > 0 else 0
        else:
            sharpe_ratio = 0
        
        # 平均持仓时间
        avg_trade_duration = np.mean([trade.duration for trade in trades])
        
        return BacktestResult(
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=win_rate,
            total_pnl=total_pnl,
            total_return=total_return,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe_ratio,
            avg_trade_duration=avg_trade_duration,
            trades=trades
        )
    
    def analyze_signal_effectiveness(self) -> Dict[str, Any]:
        """
        分析信号有效性
        
        Returns:
            信号分析结果
        """
        # 获取所有信号
        all_signals = self.signal_detector.get_all_signals()
        
        # 分析各种信号的表现
        signal_analysis = {}
        
        for signal_name, signal_data in all_signals.items():
            if isinstance(signal_data, pd.Series) and signal_data.dtype == bool:
                # 计算信号出现频率
                signal_frequency = signal_data.sum() / len(signal_data)
                
                # 计算信号后的价格变化
                price_changes = []
                for i in range(len(signal_data)):
                    if signal_data.iloc[i]:
                        # 计算信号后1天、3天、7天的价格变化
                        if i + 1 < len(self.data):
                            change_1d = (self.data['close'].iloc[i + 1] - self.data['close'].iloc[i]) / self.data['close'].iloc[i]
                            price_changes.append(change_1d)
                
                signal_analysis[signal_name] = {
                    'frequency': signal_frequency,
                    'avg_price_change_1d': np.mean(price_changes) if price_changes else 0,
                    'positive_rate': sum(1 for change in price_changes if change > 0) / len(price_changes) if price_changes else 0
                }
        
        return signal_analysis
    
    def optimize_parameters(self, 
                          param_ranges: Dict[str, List[Any]]) -> Dict[str, Any]:
        """
        优化策略参数
        
        Args:
            param_ranges: 参数范围字典
            
        Returns:
            最优参数
        """
        best_params = {}
        best_return = -float('inf')
        
        # 这里可以实现网格搜索或其他优化算法
        # 由于参数空间可能很大，这里只做简单示例
        
        for param_name, param_values in param_ranges.items():
            best_param_value = None
            best_param_return = -float('inf')
            
            for param_value in param_values:
                # 根据参数调整策略
                if param_name == 'rsi_oversold':
                    entry_signals = self.signal_detector.get_rsi_signals(oversold=param_value)[0]
                elif param_name == 'rsi_overbought':
                    exit_signals = self.signal_detector.get_rsi_signals(overbought=param_value)[1]
                else:
                    continue
                
                # 运行回测
                result = self.run_backtest(entry_signals=entry_signals, exit_signals=exit_signals)
                
                # 评估结果
                if result.total_return > best_param_return:
                    best_param_return = result.total_return
                    best_param_value = param_value
            
            best_params[param_name] = best_param_value
        
        return best_params
    
    def generate_trading_report(self, result: BacktestResult) -> str:
        """
        生成交易报告
        
        Args:
            result: 回测结果
            
        Returns:
            交易报告字符串
        """
        report = f"""
=== 交易策略回测报告 ===

基础统计:
- 总交易次数: {result.total_trades}
- 盈利交易: {result.winning_trades}
- 亏损交易: {result.losing_trades}
- 胜率: {result.win_rate:.2%}

收益统计:
- 总盈亏: {result.total_pnl:.2f}
- 总收益率: {result.total_return:.2%}
- 最大回撤: {result.max_drawdown:.2f}
- 夏普比率: {result.sharpe_ratio:.2f}

交易统计:
- 平均持仓天数: {result.avg_trade_duration:.1f}天

详细交易记录:
"""
        
        for i, trade in enumerate(result.trades[:10]):  # 只显示前10笔交易
            report += f"""
交易 {i+1}:
- 入场时间: {trade.entry_time}
- 出场时间: {trade.exit_time}
- 入场价格: {trade.entry_price:.4f}
- 出场价格: {trade.exit_price:.4f}
- 盈亏: {trade.pnl:.2f} ({trade.pnl_percent:.2%})
- 持仓天数: {trade.duration}天
- 信号强度: {trade.signal_strength:.2f}
"""
        
        if len(result.trades) > 10:
            report += f"\n... 还有 {len(result.trades) - 10} 笔交易未显示"
        
        return report
