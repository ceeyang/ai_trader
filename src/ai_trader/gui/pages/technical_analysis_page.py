"""
技术分析页面
提供技术指标计算、K线形态识别和交易信号检测的GUI界面
"""

import tkinter as tk
from tkinter import ttk, messagebox
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import threading

from ...core.data.providers.binance import BinanceDataSource
from ...core.analysis import TechnicalIndicators, CandlestickPatterns, SignalDetector, BacktestEngine


class TechnicalAnalysisPage:
    """技术分析页面类"""
    
    def __init__(self, parent: ttk.Frame):
        """
        初始化技术分析页面
        
        Args:
            parent: 父容器
        """
        self.parent = parent
        self.data_source: Optional[BinanceDataSource] = None
        self.historical_data: Optional[pd.DataFrame] = None
        self.indicators: Optional[TechnicalIndicators] = None
        self.patterns: Optional[CandlestickPatterns] = None
        self.signal_detector: Optional[SignalDetector] = None
        
        # 创建页面
        self.create_widgets()
        
        # 初始化数据源
        self.init_data_source()
    
    def create_widgets(self) -> None:
        """创建页面组件"""
        # 主框架
        main_frame = ttk.Frame(self.parent)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # 创建滚动区域
        canvas = tk.Canvas(main_frame)
        scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # 数据获取区域
        self.create_data_section(scrollable_frame)
        
        # 技术指标区域
        self.create_indicators_section(scrollable_frame)
        
        # K线形态区域
        self.create_patterns_section(scrollable_frame)
        
        # 信号检测区域
        self.create_signals_section(scrollable_frame)
        
        # 回测分析区域
        self.create_backtest_section(scrollable_frame)
        
        # 结果显示区域
        self.create_results_section(scrollable_frame)
        
        # 布局滚动区域
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
    
    def create_data_section(self, parent: ttk.Frame) -> None:
        """创建数据获取区域"""
        # 数据获取框架
        data_frame = ttk.LabelFrame(parent, text="数据获取", padding=10)
        data_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)
        data_frame.columnconfigure(1, weight=1)
        
        # 币种选择
        ttk.Label(data_frame, text="交易对:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        self.symbol_var = tk.StringVar(value="BTCUSDT")
        self.symbol_combo = ttk.Combobox(data_frame, textvariable=self.symbol_var, 
                                        state="readonly", width=15)
        self.symbol_combo.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(0, 10))
        
        # 主流币种筛选
        self.mainstream_only = tk.BooleanVar(value=True)
        mainstream_check = ttk.Checkbutton(data_frame, text="仅显示主流货币", 
                                         variable=self.mainstream_only,
                                         command=self.load_symbols)
        mainstream_check.grid(row=0, column=2, sticky=tk.W, padx=(10, 0))
        
        # 时间范围
        ttk.Label(data_frame, text="时间范围:").grid(row=1, column=0, sticky=tk.W, padx=(0, 5), pady=(10, 0))
        
        # 开始日期
        ttk.Label(data_frame, text="开始日期:").grid(row=1, column=1, sticky=tk.W, padx=(0, 5), pady=(10, 0))
        self.start_date_var = tk.StringVar(value=(datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d'))
        start_date_entry = ttk.Entry(data_frame, textvariable=self.start_date_var, width=12)
        start_date_entry.grid(row=1, column=2, sticky=tk.W, padx=(0, 10), pady=(10, 0))
        
        # 结束日期
        ttk.Label(data_frame, text="结束日期:").grid(row=1, column=3, sticky=tk.W, padx=(0, 5), pady=(10, 0))
        self.end_date_var = tk.StringVar(value=datetime.now().strftime('%Y-%m-%d'))
        end_date_entry = ttk.Entry(data_frame, textvariable=self.end_date_var, width=12)
        end_date_entry.grid(row=1, column=4, sticky=tk.W, padx=(0, 10), pady=(10, 0))
        
        # 时间周期
        ttk.Label(data_frame, text="时间周期:").grid(row=2, column=0, sticky=tk.W, padx=(0, 5), pady=(10, 0))
        self.interval_var = tk.StringVar(value="1d")
        interval_combo = ttk.Combobox(data_frame, textvariable=self.interval_var, 
                                     values=["1m", "5m", "15m", "1h", "4h", "1d"], 
                                     state="readonly", width=8)
        interval_combo.grid(row=2, column=1, sticky=tk.W, padx=(0, 10), pady=(10, 0))
        
        # 获取数据按钮
        self.load_data_btn = ttk.Button(data_frame, text="获取数据", command=self.load_historical_data)
        self.load_data_btn.grid(row=2, column=2, sticky=tk.W, padx=(10, 0), pady=(10, 0))
        
        # 数据状态标签
        self.data_status_label = ttk.Label(data_frame, text="未加载数据", foreground="red")
        self.data_status_label.grid(row=2, column=3, sticky=tk.W, padx=(10, 0), pady=(10, 0))
        
        # 加载币种列表
        self.load_symbols()
    
    def create_indicators_section(self, parent: ttk.Frame) -> None:
        """创建技术指标区域"""
        # 技术指标框架
        indicators_frame = ttk.LabelFrame(parent, text="技术指标设置", padding=10)
        indicators_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)
        indicators_frame.columnconfigure(1, weight=1)
        
        # 移动平均线设置
        ma_frame = ttk.Frame(indicators_frame)
        ma_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)
        ma_frame.columnconfigure(1, weight=1)
        
        ttk.Label(ma_frame, text="移动平均线周期:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        self.sma_periods = tk.StringVar(value="5,10,20,50,200")
        sma_entry = ttk.Entry(ma_frame, textvariable=self.sma_periods, width=20)
        sma_entry.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(0, 10))
        
        # MACD设置
        macd_frame = ttk.Frame(indicators_frame)
        macd_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)
        
        ttk.Label(macd_frame, text="MACD参数:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        ttk.Label(macd_frame, text="快线:").grid(row=0, column=1, sticky=tk.W, padx=(0, 2))
        self.macd_fast = tk.StringVar(value="12")
        macd_fast_entry = ttk.Entry(macd_frame, textvariable=self.macd_fast, width=5)
        macd_fast_entry.grid(row=0, column=2, sticky=tk.W, padx=(0, 5))
        
        ttk.Label(macd_frame, text="慢线:").grid(row=0, column=3, sticky=tk.W, padx=(0, 2))
        self.macd_slow = tk.StringVar(value="26")
        macd_slow_entry = ttk.Entry(macd_frame, textvariable=self.macd_slow, width=5)
        macd_slow_entry.grid(row=0, column=4, sticky=tk.W, padx=(0, 5))
        
        ttk.Label(macd_frame, text="信号线:").grid(row=0, column=5, sticky=tk.W, padx=(0, 2))
        self.macd_signal = tk.StringVar(value="9")
        macd_signal_entry = ttk.Entry(macd_frame, textvariable=self.macd_signal, width=5)
        macd_signal_entry.grid(row=0, column=6, sticky=tk.W, padx=(0, 10))
        
        # RSI设置
        rsi_frame = ttk.Frame(indicators_frame)
        rsi_frame.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)
        
        ttk.Label(rsi_frame, text="RSI参数:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        ttk.Label(rsi_frame, text="周期:").grid(row=0, column=1, sticky=tk.W, padx=(0, 2))
        self.rsi_period = tk.StringVar(value="14")
        rsi_period_entry = ttk.Entry(rsi_frame, textvariable=self.rsi_period, width=5)
        rsi_period_entry.grid(row=0, column=2, sticky=tk.W, padx=(0, 10))
        
        ttk.Label(rsi_frame, text="超卖阈值:").grid(row=0, column=3, sticky=tk.W, padx=(0, 2))
        self.rsi_oversold = tk.StringVar(value="30")
        rsi_oversold_entry = ttk.Entry(rsi_frame, textvariable=self.rsi_oversold, width=5)
        rsi_oversold_entry.grid(row=0, column=4, sticky=tk.W, padx=(0, 5))
        
        ttk.Label(rsi_frame, text="超买阈值:").grid(row=0, column=5, sticky=tk.W, padx=(0, 2))
        self.rsi_overbought = tk.StringVar(value="70")
        rsi_overbought_entry = ttk.Entry(rsi_frame, textvariable=self.rsi_overbought, width=5)
        rsi_overbought_entry.grid(row=0, column=6, sticky=tk.W, padx=(0, 10))
        
        # KDJ设置
        kdj_frame = ttk.Frame(indicators_frame)
        kdj_frame.grid(row=3, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)
        
        ttk.Label(kdj_frame, text="KDJ参数:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        ttk.Label(kdj_frame, text="K周期:").grid(row=0, column=1, sticky=tk.W, padx=(0, 2))
        self.kdj_k_period = tk.StringVar(value="9")
        kdj_k_entry = ttk.Entry(kdj_frame, textvariable=self.kdj_k_period, width=5)
        kdj_k_entry.grid(row=0, column=2, sticky=tk.W, padx=(0, 5))
        
        ttk.Label(kdj_frame, text="D周期:").grid(row=0, column=3, sticky=tk.W, padx=(0, 2))
        self.kdj_d_period = tk.StringVar(value="3")
        kdj_d_entry = ttk.Entry(kdj_frame, textvariable=self.kdj_d_period, width=5)
        kdj_d_entry.grid(row=0, column=4, sticky=tk.W, padx=(0, 5))
        
        ttk.Label(kdj_frame, text="J周期:").grid(row=0, column=5, sticky=tk.W, padx=(0, 2))
        self.kdj_j_period = tk.StringVar(value="3")
        kdj_j_entry = ttk.Entry(kdj_frame, textvariable=self.kdj_j_period, width=5)
        kdj_j_entry.grid(row=0, column=6, sticky=tk.W, padx=(0, 10))
        
        # 布林带设置
        bb_frame = ttk.Frame(indicators_frame)
        bb_frame.grid(row=4, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)
        
        ttk.Label(bb_frame, text="布林带参数:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        ttk.Label(bb_frame, text="周期:").grid(row=0, column=1, sticky=tk.W, padx=(0, 2))
        self.bb_period = tk.StringVar(value="20")
        bb_period_entry = ttk.Entry(bb_frame, textvariable=self.bb_period, width=5)
        bb_period_entry.grid(row=0, column=2, sticky=tk.W, padx=(0, 5))
        
        ttk.Label(bb_frame, text="标准差倍数:").grid(row=0, column=3, sticky=tk.W, padx=(0, 2))
        self.bb_std_dev = tk.StringVar(value="2")
        bb_std_entry = ttk.Entry(bb_frame, textvariable=self.bb_std_dev, width=5)
        bb_std_entry.grid(row=0, column=4, sticky=tk.W, padx=(0, 10))
    
    def create_patterns_section(self, parent: ttk.Frame) -> None:
        """创建K线形态区域"""
        # K线形态框架
        patterns_frame = ttk.LabelFrame(parent, text="K线形态识别", padding=10)
        patterns_frame.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)
        
        # 单根K线形态
        single_frame = ttk.Frame(patterns_frame)
        single_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=5)
        
        ttk.Label(single_frame, text="单根K线形态:").grid(row=0, column=0, sticky=tk.W, padx=(0, 10))
        
        self.hammer_enabled = tk.BooleanVar(value=True)
        hammer_check = ttk.Checkbutton(single_frame, text="锤子线", variable=self.hammer_enabled)
        hammer_check.grid(row=0, column=1, sticky=tk.W, padx=(0, 10))
        
        self.hanging_man_enabled = tk.BooleanVar(value=True)
        hanging_man_check = ttk.Checkbutton(single_frame, text="上吊线", variable=self.hanging_man_enabled)
        hanging_man_check.grid(row=0, column=2, sticky=tk.W, padx=(0, 10))
        
        self.doji_enabled = tk.BooleanVar(value=True)
        doji_check = ttk.Checkbutton(single_frame, text="十字星", variable=self.doji_enabled)
        doji_check.grid(row=0, column=3, sticky=tk.W, padx=(0, 10))
        
        # 两根K线形态
        double_frame = ttk.Frame(patterns_frame)
        double_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=5)
        
        ttk.Label(double_frame, text="两根K线形态:").grid(row=0, column=0, sticky=tk.W, padx=(0, 10))
        
        self.bullish_engulfing_enabled = tk.BooleanVar(value=True)
        bullish_engulfing_check = ttk.Checkbutton(double_frame, text="看涨吞没", variable=self.bullish_engulfing_enabled)
        bullish_engulfing_check.grid(row=0, column=1, sticky=tk.W, padx=(0, 10))
        
        self.bearish_engulfing_enabled = tk.BooleanVar(value=True)
        bearish_engulfing_check = ttk.Checkbutton(double_frame, text="看跌吞没", variable=self.bearish_engulfing_enabled)
        bearish_engulfing_check.grid(row=0, column=2, sticky=tk.W, padx=(0, 10))
        
        # 三根K线形态
        triple_frame = ttk.Frame(patterns_frame)
        triple_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=5)
        
        ttk.Label(triple_frame, text="三根K线形态:").grid(row=0, column=0, sticky=tk.W, padx=(0, 10))
        
        self.morning_star_enabled = tk.BooleanVar(value=True)
        morning_star_check = ttk.Checkbutton(triple_frame, text="启明星", variable=self.morning_star_enabled)
        morning_star_check.grid(row=0, column=1, sticky=tk.W, padx=(0, 10))
        
        self.evening_star_enabled = tk.BooleanVar(value=True)
        evening_star_check = ttk.Checkbutton(triple_frame, text="黄昏星", variable=self.evening_star_enabled)
        evening_star_check.grid(row=0, column=2, sticky=tk.W, padx=(0, 10))
        
        self.three_white_soldiers_enabled = tk.BooleanVar(value=True)
        three_white_soldiers_check = ttk.Checkbutton(triple_frame, text="红三兵", variable=self.three_white_soldiers_enabled)
        three_white_soldiers_check.grid(row=0, column=3, sticky=tk.W, padx=(0, 10))
        
        self.three_black_crows_enabled = tk.BooleanVar(value=True)
        three_black_crows_check = ttk.Checkbutton(triple_frame, text="三只乌鸦", variable=self.three_black_crows_enabled)
        three_black_crows_check.grid(row=0, column=4, sticky=tk.W, padx=(0, 10))
    
    def create_signals_section(self, parent: ttk.Frame) -> None:
        """创建信号检测区域"""
        # 信号检测框架
        signals_frame = ttk.LabelFrame(parent, text="交易信号设置", padding=10)
        signals_frame.grid(row=3, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)
        
        # 入场信号设置
        entry_frame = ttk.Frame(signals_frame)
        entry_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=5)
        
        ttk.Label(entry_frame, text="入场信号条件:").grid(row=0, column=0, sticky=tk.W, padx=(0, 10))
        
        # 趋势条件
        self.trend_required = tk.BooleanVar(value=True)
        trend_check = ttk.Checkbutton(entry_frame, text="趋势确认", variable=self.trend_required)
        trend_check.grid(row=0, column=1, sticky=tk.W, padx=(0, 10))
        
        # 指标条件
        self.macd_required = tk.BooleanVar(value=True)
        macd_check = ttk.Checkbutton(entry_frame, text="MACD", variable=self.macd_required)
        macd_check.grid(row=0, column=2, sticky=tk.W, padx=(0, 10))
        
        self.rsi_required = tk.BooleanVar(value=True)
        rsi_check = ttk.Checkbutton(entry_frame, text="RSI", variable=self.rsi_required)
        rsi_check.grid(row=0, column=3, sticky=tk.W, padx=(0, 10))
        
        self.kdj_required = tk.BooleanVar(value=True)
        kdj_check = ttk.Checkbutton(entry_frame, text="KDJ", variable=self.kdj_required)
        kdj_check.grid(row=0, column=4, sticky=tk.W, padx=(0, 10))
        
        self.bb_required = tk.BooleanVar(value=True)
        bb_check = ttk.Checkbutton(entry_frame, text="布林带", variable=self.bb_required)
        bb_check.grid(row=0, column=5, sticky=tk.W, padx=(0, 10))
        
        # 形态条件
        self.pattern_required = tk.BooleanVar(value=True)
        pattern_check = ttk.Checkbutton(entry_frame, text="K线形态", variable=self.pattern_required)
        pattern_check.grid(row=0, column=6, sticky=tk.W, padx=(0, 10))
        
        # 成交量条件
        self.volume_required = tk.BooleanVar(value=True)
        volume_check = ttk.Checkbutton(entry_frame, text="成交量确认", variable=self.volume_required)
        volume_check.grid(row=0, column=7, sticky=tk.W, padx=(0, 10))
        
        # 信号强度设置
        strength_frame = ttk.Frame(signals_frame)
        strength_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=5)
        
        ttk.Label(strength_frame, text="信号强度阈值:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        self.signal_strength_threshold = tk.StringVar(value="0.5")
        strength_entry = ttk.Entry(strength_frame, textvariable=self.signal_strength_threshold, width=10)
        strength_entry.grid(row=0, column=1, sticky=tk.W, padx=(0, 10))
        
        # 信号组合方式
        ttk.Label(strength_frame, text="组合方式:").grid(row=0, column=2, sticky=tk.W, padx=(0, 5))
        self.signal_combination = tk.StringVar(value="all")
        combination_combo = ttk.Combobox(strength_frame, textvariable=self.signal_combination,
                                       values=["all", "any"], state="readonly", width=8)
        combination_combo.grid(row=0, column=3, sticky=tk.W, padx=(0, 10))
        
        # 最小条件数量
        ttk.Label(strength_frame, text="最少条件数:").grid(row=0, column=4, sticky=tk.W, padx=(0, 5))
        self.min_conditions = tk.StringVar(value="2")
        min_conditions_entry = ttk.Entry(strength_frame, textvariable=self.min_conditions, width=5)
        min_conditions_entry.grid(row=0, column=5, sticky=tk.W, padx=(0, 10))
        
        # 分析按钮
        button_frame = ttk.Frame(signals_frame)
        button_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(10, 0))
        
        self.analyze_btn = ttk.Button(button_frame, text="开始分析", command=self.analyze_signals)
        self.analyze_btn.grid(row=0, column=0, sticky=tk.W, padx=(0, 10))
        
        self.quick_test_btn = ttk.Button(button_frame, text="快速测试", command=self.quick_test_signals)
        self.quick_test_btn.grid(row=0, column=1, sticky=tk.W, padx=(0, 10))
        
        self.reset_btn = ttk.Button(button_frame, text="重置参数", command=self.reset_parameters)
        self.reset_btn.grid(row=0, column=2, sticky=tk.W)
    
    def create_backtest_section(self, parent: ttk.Frame) -> None:
        """创建回测分析区域"""
        # 回测框架
        backtest_frame = ttk.LabelFrame(parent, text="回测设置", padding=10)
        backtest_frame.grid(row=4, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)
        
        # 初始资金
        ttk.Label(backtest_frame, text="初始资金:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        self.initial_capital = tk.StringVar(value="100000")
        capital_entry = ttk.Entry(backtest_frame, textvariable=self.initial_capital, width=15)
        capital_entry.grid(row=0, column=1, sticky=tk.W, padx=(0, 10))
        
        # 仓位大小
        ttk.Label(backtest_frame, text="仓位大小:").grid(row=0, column=2, sticky=tk.W, padx=(0, 5))
        self.position_size = tk.StringVar(value="0.1")
        position_entry = ttk.Entry(backtest_frame, textvariable=self.position_size, width=10)
        position_entry.grid(row=0, column=3, sticky=tk.W, padx=(0, 10))
        
        # 手续费率
        ttk.Label(backtest_frame, text="手续费率:").grid(row=0, column=4, sticky=tk.W, padx=(0, 5))
        self.commission_rate = tk.StringVar(value="0.001")
        commission_entry = ttk.Entry(backtest_frame, textvariable=self.commission_rate, width=10)
        commission_entry.grid(row=0, column=5, sticky=tk.W, padx=(0, 10))
        
        # 滑点率
        ttk.Label(backtest_frame, text="滑点率:").grid(row=1, column=0, sticky=tk.W, padx=(0, 5), pady=(5, 0))
        self.slippage_rate = tk.StringVar(value="0.0005")
        slippage_entry = ttk.Entry(backtest_frame, textvariable=self.slippage_rate, width=10)
        slippage_entry.grid(row=1, column=1, sticky=tk.W, padx=(0, 10), pady=(5, 0))
        
        # 回测按钮
        self.backtest_btn = ttk.Button(backtest_frame, text="运行回测", command=self.run_backtest)
        self.backtest_btn.grid(row=1, column=2, sticky=tk.W, padx=(10, 0), pady=(5, 0))
    
    def create_results_section(self, parent: ttk.Frame) -> None:
        """创建结果显示区域"""
        # 结果框架
        results_frame = ttk.LabelFrame(parent, text="分析结果", padding=10)
        results_frame.grid(row=5, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)
        results_frame.columnconfigure(0, weight=1)
        results_frame.rowconfigure(1, weight=1)
        
        # 结果统计
        stats_frame = ttk.Frame(results_frame)
        stats_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=5)
        stats_frame.columnconfigure(1, weight=1)
        
        # 数据统计
        ttk.Label(stats_frame, text="数据条数:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        self.data_count_label = ttk.Label(stats_frame, text="0", foreground="blue")
        self.data_count_label.grid(row=0, column=1, sticky=tk.W, padx=(0, 20))
        
        # 入场信号统计
        ttk.Label(stats_frame, text="入场信号:").grid(row=0, column=2, sticky=tk.W, padx=(0, 5))
        self.entry_signals_label = ttk.Label(stats_frame, text="0", foreground="green")
        self.entry_signals_label.grid(row=0, column=3, sticky=tk.W, padx=(0, 20))
        
        # 出场信号统计
        ttk.Label(stats_frame, text="出场信号:").grid(row=0, column=4, sticky=tk.W, padx=(0, 5))
        self.exit_signals_label = ttk.Label(stats_frame, text="0", foreground="red")
        self.exit_signals_label.grid(row=0, column=5, sticky=tk.W, padx=(0, 20))
        
        # 结果文本框
        self.results_text = tk.Text(results_frame, height=15, width=80)
        results_scrollbar = ttk.Scrollbar(results_frame, orient="vertical", command=self.results_text.yview)
        self.results_text.configure(yscrollcommand=results_scrollbar.set)
        
        self.results_text.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        results_scrollbar.grid(row=1, column=1, sticky=(tk.N, tk.S), pady=5)
        
        # 清空按钮
        clear_btn = ttk.Button(results_frame, text="清空结果", command=self.clear_results)
        clear_btn.grid(row=2, column=0, sticky=tk.W, pady=(5, 0))
    
    def init_data_source(self) -> None:
        """初始化数据源"""
        try:
            self.data_source = BinanceDataSource()
            if self.data_source.connect():
                self.data_status_label.config(text="数据源已连接", foreground="green")
            else:
                self.data_status_label.config(text="数据源连接失败", foreground="red")
        except Exception as e:
            self.data_status_label.config(text=f"初始化失败: {str(e)}", foreground="red")
    
    def load_symbols(self) -> None:
        """加载币种列表"""
        def load_symbols_thread():
            try:
                if self.data_source and self.data_source.connect():
                    mainstream_only = self.mainstream_only.get()
                    symbols = self.data_source.get_available_symbols(mainstream_only)
                    self.symbol_combo['values'] = symbols
                    if symbols and not self.symbol_combo.get():
                        self.symbol_combo.set(symbols[0])
            except Exception as e:
                print(f"加载币种失败: {e}")
        
        threading.Thread(target=load_symbols_thread, daemon=True).start()
    
    def load_historical_data(self) -> None:
        """加载历史数据"""
        def load_data_thread():
            try:
                self.load_data_btn.config(state="disabled", text="加载中...")
                
                if not self.data_source:
                    self.data_status_label.config(text="数据源未初始化", foreground="red")
                    return
                
                # 解析日期
                start_date = datetime.strptime(self.start_date_var.get(), '%Y-%m-%d')
                end_date = datetime.strptime(self.end_date_var.get(), '%Y-%m-%d')
                
                # 获取数据
                self.historical_data = self.data_source.get_historical_data(
                    symbol=self.symbol_var.get(),
                    interval=self.interval_var.get(),
                    start_time=start_date,
                    end_time=end_date
                )
                
                if self.historical_data is not None and not self.historical_data.empty:
                    self.data_status_label.config(text=f"已加载 {len(self.historical_data)} 条数据", foreground="green")
                    self.data_count_label.config(text=str(len(self.historical_data)))
                    
                    # 初始化分析器
                    self.indicators = TechnicalIndicators(self.historical_data)
                    self.patterns = CandlestickPatterns(self.historical_data)
                    self.signal_detector = SignalDetector(self.historical_data)
                    
                    self.log_result(f"成功加载 {self.symbol_var.get()} 历史数据")
                    self.log_result(f"时间范围: {self.historical_data.index[0].strftime('%Y-%m-%d')} 到 {self.historical_data.index[-1].strftime('%Y-%m-%d')}")
                    self.log_result(f"价格范围: {self.historical_data['low'].min():.2f} - {self.historical_data['high'].max():.2f}")
                else:
                    self.data_status_label.config(text="数据加载失败", foreground="red")
                    
            except Exception as e:
                self.data_status_label.config(text=f"加载失败: {str(e)}", foreground="red")
                self.log_result(f"数据加载失败: {str(e)}")
            finally:
                self.load_data_btn.config(state="normal", text="获取数据")
        
        threading.Thread(target=load_data_thread, daemon=True).start()
    
    def analyze_signals(self) -> None:
        """分析交易信号"""
        if self.historical_data is None:
            messagebox.showerror("错误", "请先加载历史数据")
            return
        
        try:
            self.analyze_btn.config(state="disabled", text="分析中...")
            
            # 重新创建信号检测器（使用自定义参数）
            signal_detector = self.create_custom_signal_detector()
            
            # 获取信号
            entry_signals = signal_detector.get_comprehensive_entry_signals()
            exit_signals = signal_detector.get_comprehensive_exit_signals()
            
            # 更新统计
            self.entry_signals_label.config(text=str(entry_signals.sum()))
            self.exit_signals_label.config(text=str(exit_signals.sum()))
            
            # 显示结果
            self.log_result(f"\n=== 信号分析结果 ===")
            self.log_result(f"入场信号: {entry_signals.sum()} 个")
            self.log_result(f"出场信号: {exit_signals.sum()} 个")
            
            # 显示具体的信号点
            if entry_signals.sum() > 0:
                self.log_result(f"\n入场机会:")
                entry_opportunities = self.historical_data[entry_signals]
                for date, row in entry_opportunities.tail(10).iterrows():
                    self.log_result(f"  {date.strftime('%Y-%m-%d')}: 价格 {row['close']:.2f}")
            
            if exit_signals.sum() > 0:
                self.log_result(f"\n出场机会:")
                exit_opportunities = self.historical_data[exit_signals]
                for date, row in exit_opportunities.tail(10).iterrows():
                    self.log_result(f"  {date.strftime('%Y-%m-%d')}: 价格 {row['close']:.2f}")
            
            # 分析信号有效性
            self.analyze_signal_effectiveness(signal_detector)
            
        except Exception as e:
            self.log_result(f"信号分析失败: {str(e)}")
            messagebox.showerror("错误", f"信号分析失败: {str(e)}")
        finally:
            self.analyze_btn.config(state="normal", text="开始分析")
    
    def create_custom_signal_detector(self) -> SignalDetector:
        """创建自定义信号检测器"""
        # 创建自定义的信号检测器，使用用户设置的参数
        class CustomSignalDetector(SignalDetector):
            def __init__(self, data, parent_detector):
                super().__init__(data)
                self.parent_detector = parent_detector
            
            def get_custom_entry_signals(self):
                """获取自定义入场信号"""
                # 获取各种信号
                trend = self.get_trend_direction()
                macd_bullish, _ = self.get_macd_signals()
                rsi_bullish, _ = self.get_rsi_signals(
                    oversold=int(self.parent_detector.rsi_oversold.get()),
                    overbought=int(self.parent_detector.rsi_overbought.get())
                )
                kdj_bullish, _ = self.get_kdj_signals()
                bb_bullish, _ = self.get_bollinger_signals()
                breakout_up, _ = self.get_breakout_signals()
                volume_conf = self.get_volume_confirmation()
                
                # 获取K线形态
                patterns = CandlestickPatterns(self.data)
                bullish_patterns = patterns.get_bullish_patterns()
                
                # 根据用户设置组合信号
                entry_conditions = []
                
                if self.parent_detector.trend_required.get():
                    entry_conditions.append(trend == 1)
                
                if self.parent_detector.macd_required.get():
                    entry_conditions.append(macd_bullish)
                
                if self.parent_detector.rsi_required.get():
                    entry_conditions.append(rsi_bullish)
                
                if self.parent_detector.kdj_required.get():
                    entry_conditions.append(kdj_bullish)
                
                if self.parent_detector.bb_required.get():
                    entry_conditions.append(bb_bullish)
                
                if self.parent_detector.pattern_required.get():
                    entry_conditions.append(bullish_patterns)
                
                if self.parent_detector.volume_required.get():
                    entry_conditions.append(volume_conf)
                
                # 根据用户设置组合条件
                if entry_conditions:
                    combination_mode = self.parent_detector.signal_combination.get()
                    min_conditions = int(self.parent_detector.min_conditions.get())
                    
                    if combination_mode == "all":
                        # 需要满足所有条件
                        combined_signals = entry_conditions[0]
                        for condition in entry_conditions[1:]:
                            combined_signals = combined_signals & condition
                        return combined_signals
                    else:
                        # 需要满足最少条件数量
                        if len(entry_conditions) >= min_conditions:
                            # 计算每个时间点满足的条件数量
                            condition_count = pd.Series(0, index=self.data.index)
                            for condition in entry_conditions:
                                condition_count += condition.astype(int)
                            
                            # 满足最少条件数量的信号
                            return condition_count >= min_conditions
                        else:
                            return pd.Series(False, index=self.data.index)
                else:
                    return pd.Series(False, index=self.data.index)
            
            def get_custom_exit_signals(self):
                """获取自定义出场信号"""
                # 获取各种信号
                trend = self.get_trend_direction()
                _, macd_bearish = self.get_macd_signals()
                _, rsi_bearish = self.get_rsi_signals(
                    oversold=int(self.parent_detector.rsi_oversold.get()),
                    overbought=int(self.parent_detector.rsi_overbought.get())
                )
                _, kdj_bearish = self.get_kdj_signals()
                _, bb_bearish = self.get_bollinger_signals()
                _, breakout_down = self.get_breakout_signals()
                
                # 获取K线形态
                patterns = CandlestickPatterns(self.data)
                bearish_patterns = patterns.get_bearish_patterns()
                
                # 根据用户设置组合信号（满足任一条件即可出场）
                exit_conditions = []
                
                if self.parent_detector.trend_required.get():
                    exit_conditions.append(trend == -1)
                
                if self.parent_detector.macd_required.get():
                    exit_conditions.append(macd_bearish)
                
                if self.parent_detector.rsi_required.get():
                    exit_conditions.append(rsi_bearish)
                
                if self.parent_detector.kdj_required.get():
                    exit_conditions.append(kdj_bearish)
                
                if self.parent_detector.bb_required.get():
                    exit_conditions.append(bb_bearish)
                
                if self.parent_detector.pattern_required.get():
                    exit_conditions.append(bearish_patterns)
                
                # 组合条件（满足任一条件即可）
                if exit_conditions:
                    combined_signals = exit_conditions[0]
                    for condition in exit_conditions[1:]:
                        combined_signals = combined_signals | condition
                    return combined_signals
                else:
                    return pd.Series(False, index=self.data.index)
        
        # 创建自定义检测器
        custom_detector = CustomSignalDetector(self.historical_data, self)
        
        # 重写方法
        custom_detector.get_comprehensive_entry_signals = custom_detector.get_custom_entry_signals
        custom_detector.get_comprehensive_exit_signals = custom_detector.get_custom_exit_signals
        
        return custom_detector
    
    def analyze_signal_effectiveness(self, signal_detector: SignalDetector) -> None:
        """分析信号有效性"""
        try:
            # 获取所有信号
            all_signals = signal_detector.get_all_signals()
            
            self.log_result(f"\n=== 信号有效性分析 ===")
            
            # 分析各种信号的表现
            for signal_name, signal_data in all_signals.items():
                if isinstance(signal_data, pd.Series) and signal_data.dtype == bool:
                    frequency = signal_data.sum() / len(signal_data)
                    if frequency > 0:
                        # 计算信号后的价格变化
                        price_changes = []
                        for i in range(len(signal_data)):
                            if signal_data.iloc[i] and i + 1 < len(self.historical_data):
                                change = (self.historical_data['close'].iloc[i + 1] - 
                                         self.historical_data['close'].iloc[i]) / self.historical_data['close'].iloc[i]
                                price_changes.append(change)
                        
                        if price_changes:
                            avg_change = np.mean(price_changes)
                            positive_rate = sum(1 for change in price_changes if change > 0) / len(price_changes)
                            
                            self.log_result(f"{signal_name}:")
                            self.log_result(f"  频率: {frequency:.2%}")
                            self.log_result(f"  平均1日收益: {avg_change:.2%}")
                            self.log_result(f"  正收益比例: {positive_rate:.2%}")
                            
        except Exception as e:
            self.log_result(f"信号有效性分析失败: {str(e)}")
    
    def run_backtest(self) -> None:
        """运行回测"""
        if self.historical_data is None:
            messagebox.showerror("错误", "请先加载历史数据")
            return
        
        try:
            self.backtest_btn.config(state="disabled", text="回测中...")
            
            # 创建回测引擎
            initial_capital = float(self.initial_capital.get())
            backtest_engine = BacktestEngine(self.historical_data, initial_capital)
            
            # 运行回测
            result = backtest_engine.run_backtest()
            
            # 显示结果
            self.log_result(f"\n=== 回测结果 ===")
            self.log_result(f"总交易次数: {result.total_trades}")
            self.log_result(f"盈利交易: {result.winning_trades}")
            self.log_result(f"亏损交易: {result.losing_trades}")
            self.log_result(f"胜率: {result.win_rate:.2%}")
            self.log_result(f"总收益率: {result.total_return:.2%}")
            self.log_result(f"最大回撤: {result.max_drawdown:.2f}")
            self.log_result(f"夏普比率: {result.sharpe_ratio:.2f}")
            self.log_result(f"平均持仓天数: {result.avg_trade_duration:.1f}天")
            
            # 显示详细交易记录
            if result.trades:
                self.log_result(f"\n=== 详细交易记录 ===")
                for i, trade in enumerate(result.trades[:10]):  # 只显示前10笔
                    self.log_result(f"交易 {i+1}:")
                    self.log_result(f"  入场: {trade.entry_time.strftime('%Y-%m-%d')} {trade.entry_price:.2f}")
                    self.log_result(f"  出场: {trade.exit_time.strftime('%Y-%m-%d')} {trade.exit_price:.2f}")
                    self.log_result(f"  盈亏: {trade.pnl:.2f} ({trade.pnl_percent:.2%})")
                    self.log_result(f"  持仓: {trade.duration}天")
            
        except Exception as e:
            self.log_result(f"回测失败: {str(e)}")
            messagebox.showerror("错误", f"回测失败: {str(e)}")
        finally:
            self.backtest_btn.config(state="normal", text="运行回测")
    
    def log_result(self, message: str) -> None:
        """记录结果到文本框"""
        self.results_text.insert(tk.END, message + "\n")
        self.results_text.see(tk.END)
    
    def clear_results(self) -> None:
        """清空结果"""
        self.results_text.delete(1.0, tk.END)
        self.entry_signals_label.config(text="0")
        self.exit_signals_label.config(text="0")
        self.data_count_label.config(text="0")
    
    def quick_test_signals(self) -> None:
        """快速测试信号"""
        if self.historical_data is None:
            messagebox.showerror("错误", "请先加载历史数据")
            return
        
        try:
            self.quick_test_btn.config(state="disabled", text="测试中...")
            
            self.log_result(f"\n=== 快速信号测试 ===")
            
            # 测试不同的参数组合
            test_configs = [
                {"name": "宽松模式", "combination": "any", "min_conditions": "1", "rsi_oversold": "40", "rsi_overbought": "60"},
                {"name": "平衡模式", "combination": "any", "min_conditions": "2", "rsi_oversold": "30", "rsi_overbought": "70"},
                {"name": "严格模式", "combination": "all", "min_conditions": "3", "rsi_oversold": "25", "rsi_overbought": "75"},
                {"name": "仅RSI", "combination": "any", "min_conditions": "1", "rsi_oversold": "30", "rsi_overbought": "70"},
                {"name": "仅MACD", "combination": "any", "min_conditions": "1", "rsi_oversold": "30", "rsi_overbought": "70"}
            ]
            
            for config in test_configs:
                self.log_result(f"\n测试配置: {config['name']}")
                
                # 临时设置参数
                original_combination = self.signal_combination.get()
                original_min_conditions = self.min_conditions.get()
                original_rsi_oversold = self.rsi_oversold.get()
                original_rsi_overbought = self.rsi_overbought.get()
                
                self.signal_combination.set(config["combination"])
                self.min_conditions.set(config["min_conditions"])
                self.rsi_oversold.set(config["rsi_oversold"])
                self.rsi_overbought.set(config["rsi_overbought"])
                
                # 根据配置设置条件
                if config["name"] == "仅RSI":
                    self.trend_required.set(False)
                    self.macd_required.set(False)
                    self.rsi_required.set(True)
                    self.kdj_required.set(False)
                    self.bb_required.set(False)
                    self.pattern_required.set(False)
                    self.volume_required.set(False)
                elif config["name"] == "仅MACD":
                    self.trend_required.set(False)
                    self.macd_required.set(True)
                    self.rsi_required.set(False)
                    self.kdj_required.set(False)
                    self.bb_required.set(False)
                    self.pattern_required.set(False)
                    self.volume_required.set(False)
                else:
                    # 恢复默认设置
                    self.trend_required.set(True)
                    self.macd_required.set(True)
                    self.rsi_required.set(True)
                    self.kdj_required.set(True)
                    self.bb_required.set(True)
                    self.pattern_required.set(True)
                    self.volume_required.set(True)
                
                # 测试信号
                signal_detector = self.create_custom_signal_detector()
                entry_signals = signal_detector.get_comprehensive_entry_signals()
                exit_signals = signal_detector.get_comprehensive_exit_signals()
                
                self.log_result(f"  入场信号: {entry_signals.sum()} 个")
                self.log_result(f"  出场信号: {exit_signals.sum()} 个")
                
                # 恢复原始参数
                self.signal_combination.set(original_combination)
                self.min_conditions.set(original_min_conditions)
                self.rsi_oversold.set(original_rsi_oversold)
                self.rsi_overbought.set(original_rsi_overbought)
            
            # 恢复默认条件设置
            self.trend_required.set(True)
            self.macd_required.set(True)
            self.rsi_required.set(True)
            self.kdj_required.set(True)
            self.bb_required.set(True)
            self.pattern_required.set(True)
            self.volume_required.set(True)
            
            self.log_result(f"\n快速测试完成！请根据结果调整参数。")
            
        except Exception as e:
            self.log_result(f"快速测试失败: {str(e)}")
            messagebox.showerror("错误", f"快速测试失败: {str(e)}")
        finally:
            self.quick_test_btn.config(state="normal", text="快速测试")
    
    def reset_parameters(self) -> None:
        """重置参数到默认值"""
        # 重置技术指标参数
        self.sma_periods.set("5,10,20,50,200")
        self.macd_fast.set("12")
        self.macd_slow.set("26")
        self.macd_signal.set("9")
        self.rsi_period.set("14")
        self.rsi_oversold.set("30")
        self.rsi_overbought.set("70")
        self.kdj_k_period.set("9")
        self.kdj_d_period.set("3")
        self.kdj_j_period.set("3")
        self.bb_period.set("20")
        self.bb_std_dev.set("2")
        
        # 重置K线形态
        self.hammer_enabled.set(True)
        self.hanging_man_enabled.set(True)
        self.doji_enabled.set(True)
        self.bullish_engulfing_enabled.set(True)
        self.bearish_engulfing_enabled.set(True)
        self.morning_star_enabled.set(True)
        self.evening_star_enabled.set(True)
        self.three_white_soldiers_enabled.set(True)
        self.three_black_crows_enabled.set(True)
        
        # 重置信号条件
        self.trend_required.set(True)
        self.macd_required.set(True)
        self.rsi_required.set(True)
        self.kdj_required.set(True)
        self.bb_required.set(True)
        self.pattern_required.set(True)
        self.volume_required.set(True)
        
        # 重置信号设置
        self.signal_strength_threshold.set("0.5")
        self.signal_combination.set("all")
        self.min_conditions.set("2")
        
        # 重置回测参数
        self.initial_capital.set("100000")
        self.position_size.set("0.1")
        self.commission_rate.set("0.001")
        self.slippage_rate.set("0.0005")
        
        self.log_result("参数已重置为默认值")
