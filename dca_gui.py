#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
定投收益计算器 - 跨平台GUI应用程序
支持Windows、macOS、Linux
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import requests
from datetime import datetime, timedelta
import threading
import json
from typing import List, Dict, Optional

# ------------------------------
# 配置部分
# ------------------------------
BINANCE_API = "https://api.binance.com/api/v3/klines"
BINANCE_TICKER_API = "https://api.binance.com/api/v3/ticker/price"
BINANCE_SYMBOLS_API = "https://api.binance.com/api/v3/exchangeInfo"

class DCACalculatorGUI:
    """定投收益计算器GUI主类"""
    
    def __init__(self, root: tk.Tk) -> None:
        """
        初始化GUI应用程序
        :param root: tkinter根窗口
        """
        self.root = root
        self.root.title("定投收益计算器")
        self.root.geometry("800x700")
        self.root.resizable(True, True)
        
        # 设置样式
        self.setup_styles()
        
        # 初始化变量
        self.symbols_list: List[str] = []
        self.current_price: float = 0.0
        
        # 创建GUI组件
        self.create_widgets()
        
        # 加载币种列表
        self.load_symbols()
    
    def setup_styles(self) -> None:
        """设置GUI样式"""
        style = ttk.Style()
        style.theme_use('clam')
        
        # 配置样式
        style.configure('Title.TLabel', font=('Arial', 16, 'bold'))
        style.configure('Header.TLabel', font=('Arial', 12, 'bold'))
        style.configure('Info.TLabel', font=('Arial', 10))
    
    def create_widgets(self) -> None:
        """创建GUI组件"""
        # 主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 配置网格权重
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        
        # 标题
        title_label = ttk.Label(main_frame, text="定投收益计算器", style='Title.TLabel')
        title_label.grid(row=0, column=0, columnspan=2, pady=(0, 20))
        
        # 币种选择
        ttk.Label(main_frame, text="选择币种:", style='Header.TLabel').grid(row=1, column=0, sticky=tk.W, pady=5)
        self.symbol_var = tk.StringVar(value="SOLUSDT")
        self.symbol_combo = ttk.Combobox(main_frame, textvariable=self.symbol_var, width=20, state="readonly")
        self.symbol_combo.grid(row=1, column=1, sticky=(tk.W, tk.E), pady=5, padx=(10, 0))
        
        # 开始日期选择
        ttk.Label(main_frame, text="开始日期:", style='Header.TLabel').grid(row=2, column=0, sticky=tk.W, pady=5)
        self.start_date_var = tk.StringVar(value="2024-01-01")
        self.start_date_entry = ttk.Entry(main_frame, textvariable=self.start_date_var, width=20)
        self.start_date_entry.grid(row=2, column=1, sticky=(tk.W, tk.E), pady=5, padx=(10, 0))
        
        # 结束日期选择
        ttk.Label(main_frame, text="结束日期:", style='Header.TLabel').grid(row=3, column=0, sticky=tk.W, pady=5)
        self.end_date_var = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d"))
        self.end_date_entry = ttk.Entry(main_frame, textvariable=self.end_date_var, width=20)
        self.end_date_entry.grid(row=3, column=1, sticky=(tk.W, tk.E), pady=5, padx=(10, 0))
        
        # 定投日期选择
        ttk.Label(main_frame, text="定投日期:", style='Header.TLabel').grid(row=4, column=0, sticky=tk.W, pady=5)
        self.invest_day_var = tk.StringVar(value="10")
        self.invest_day_combo = ttk.Combobox(main_frame, textvariable=self.invest_day_var, 
                                           values=[str(i) for i in range(1, 32)], width=20, state="readonly")
        self.invest_day_combo.grid(row=4, column=1, sticky=(tk.W, tk.E), pady=5, padx=(10, 0))
        
        # 定投金额
        ttk.Label(main_frame, text="定投金额 (USDT):", style='Header.TLabel').grid(row=5, column=0, sticky=tk.W, pady=5)
        self.invest_amount_var = tk.StringVar(value="200")
        self.invest_amount_entry = ttk.Entry(main_frame, textvariable=self.invest_amount_var, width=20)
        self.invest_amount_entry.grid(row=5, column=1, sticky=(tk.W, tk.E), pady=5, padx=(10, 0))
        
        # 按钮框架
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=6, column=0, columnspan=2, pady=20)
        
        # 计算按钮
        self.calculate_btn = ttk.Button(button_frame, text="计算收益", command=self.calculate_profit)
        self.calculate_btn.pack(side=tk.LEFT, padx=5)
        
        # 清空按钮
        self.clear_btn = ttk.Button(button_frame, text="清空结果", command=self.clear_results)
        self.clear_btn.pack(side=tk.LEFT, padx=5)
        
        # 结果显示区域
        ttk.Label(main_frame, text="计算结果:", style='Header.TLabel').grid(row=7, column=0, sticky=tk.W, pady=(20, 5))
        
        # 创建结果显示的文本框
        self.result_text = scrolledtext.ScrolledText(main_frame, height=15, width=80, wrap=tk.WORD)
        self.result_text.grid(row=8, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        
        # 配置网格权重
        main_frame.rowconfigure(8, weight=1)
    
    def load_symbols(self) -> None:
        """加载币种列表"""
        def load_symbols_thread():
            try:
                response = requests.get(BINANCE_SYMBOLS_API, timeout=10)
                data = response.json()
                symbols = []
                for symbol_info in data['symbols']:
                    if symbol_info['status'] == 'TRADING' and symbol_info['symbol'].endswith('USDT'):
                        symbols.append(symbol_info['symbol'])
                
                # 按字母顺序排序
                symbols.sort()
                self.symbols_list = symbols
                
                # 更新下拉框
                self.root.after(0, self.update_symbol_combo)
                
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("错误", f"加载币种列表失败: {str(e)}"))
        
        # 在后台线程中加载币种
        threading.Thread(target=load_symbols_thread, daemon=True).start()
    
    def update_symbol_combo(self) -> None:
        """更新币种下拉框"""
        self.symbol_combo['values'] = self.symbols_list
        if not self.symbols_list:
            self.symbols_list = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "ADAUSDT"]
            self.symbol_combo['values'] = self.symbols_list
    
    def get_historical_data(self, symbol: str, start_date: str, end_date: str) -> List[Dict]:
        """
        获取历史K线数据
        :param symbol: 交易对符号
        :param start_date: 开始日期
        :param end_date: 结束日期
        :return: K线数据列表
        """
        try:
            # 计算时间范围
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            days_diff = (end_dt - start_dt).days
            
            # 获取足够的数据
            limit = min(days_diff + 50, 1000)
            
            params = {
                "symbol": symbol,
                "interval": "1d",
                "limit": limit
            }
            
            response = requests.get(BINANCE_API, params=params, timeout=10)
            data = response.json()
            
            klines = []
            for k in data:
                open_time = datetime.fromtimestamp(k[0]/1000)
                close_price = float(k[4])
                klines.append({
                    "date": open_time.strftime("%Y-%m-%d"),
                    "datetime": open_time,
                    "close": close_price
                })
            
            return klines
            
        except Exception as e:
            raise Exception(f"获取历史数据失败: {str(e)}")
    
    def get_current_price(self, symbol: str) -> float:
        """
        获取当前实时价格
        :param symbol: 交易对符号
        :return: 当前价格
        """
        try:
            params = {"symbol": symbol}
            response = requests.get(BINANCE_TICKER_API, params=params, timeout=10)
            data = response.json()
            return float(data['price'])
        except Exception as e:
            raise Exception(f"获取当前价格失败: {str(e)}")
    
    def filter_investment_dates(self, klines: List[Dict], invest_day: int) -> List[Dict]:
        """
        筛选定投日期数据
        :param klines: K线数据列表
        :param invest_day: 定投日期
        :return: 筛选后的数据
        """
        investment_data = []
        current_month = None
        
        for kline in klines:
            kline_date = kline['datetime']
            if current_month != kline_date.month:
                current_month = kline_date.month
            
            if kline_date.day == invest_day:
                investment_data.append(kline)
        
        return investment_data
    
    def calculate_profit(self) -> None:
        """计算定投收益"""
        try:
            # 获取输入参数
            symbol = self.symbol_var.get().strip()
            start_date = self.start_date_var.get().strip()
            end_date = self.end_date_var.get().strip()
            invest_day = int(self.invest_day_var.get())
            invest_amount = float(self.invest_amount_var.get())
            
            # 验证输入
            if not symbol or not start_date or not end_date:
                messagebox.showerror("错误", "请填写所有必填字段")
                return
            
            if invest_amount <= 0:
                messagebox.showerror("错误", "定投金额必须大于0")
                return
            
            # 显示计算中状态
            self.result_text.delete(1.0, tk.END)
            self.result_text.insert(tk.END, "正在计算，请稍候...\n")
            self.calculate_btn.config(state="disabled")
            
            # 在后台线程中执行计算
            threading.Thread(target=self.calculate_profit_thread, 
                           args=(symbol, start_date, end_date, invest_day, invest_amount), 
                           daemon=True).start()
            
        except ValueError as e:
            messagebox.showerror("错误", f"输入格式错误: {str(e)}")
        except Exception as e:
            messagebox.showerror("错误", f"计算失败: {str(e)}")
    
    def calculate_profit_thread(self, symbol: str, start_date: str, end_date: str, 
                              invest_day: int, invest_amount: float) -> None:
        """在后台线程中计算收益"""
        try:
            # 获取历史数据
            klines = self.get_historical_data(symbol, start_date, end_date)
            
            # 筛选定投日期
            investment_data = self.filter_investment_dates(klines, invest_day)
            
            if not investment_data:
                self.root.after(0, lambda: self.show_error("未找到符合条件的定投日期数据"))
                return
            
            # 计算定投收益
            total_coins = 0.0
            total_invested = 0.0
            
            result_lines = []
            result_lines.append(f"币种: {symbol}")
            result_lines.append(f"定投日期: 每月{invest_day}号")
            result_lines.append(f"定投金额: {invest_amount} USDT")
            result_lines.append(f"时间范围: {start_date} 至 {end_date}")
            result_lines.append(f"找到 {len(investment_data)} 次定投记录")
            result_lines.append("-" * 50)
            result_lines.append("定投详情:")
            
            for k in investment_data:
                coins_bought = invest_amount / k['close']
                total_coins += coins_bought
                total_invested += invest_amount
                result_lines.append(f"{k['date']}: 价格={k['close']:.2f} USDT, 买入={coins_bought:.6f} {symbol}")
            
            # 获取当前价格
            current_price = self.get_current_price(symbol)
            
            # 计算收益
            total_value = total_coins * current_price
            profit = total_value - total_invested
            profit_rate = profit / total_invested * 100 if total_invested > 0 else 0
            
            result_lines.append("\n" + "=" * 50)
            result_lines.append("收益汇总:")
            result_lines.append(f"当前价格: {current_price:.2f} USDT")
            result_lines.append(f"总投入: {total_invested:.2f} USDT")
            result_lines.append(f"当前总价值: {total_value:.2f} USDT")
            result_lines.append(f"收益: {profit:.2f} USDT")
            result_lines.append(f"收益率: {profit_rate:.2f}%")
            result_lines.append(f"累计买入: {total_coins:.6f} {symbol}")
            result_lines.append(f"平均成本: {total_invested/total_coins:.2f} USDT")
            result_lines.append("=" * 50)
            
            # 更新UI
            self.root.after(0, lambda: self.show_results(result_lines))
            
        except Exception as e:
            self.root.after(0, lambda: self.show_error(f"计算失败: {str(e)}"))
    
    def show_results(self, result_lines: List[str]) -> None:
        """显示计算结果"""
        self.result_text.delete(1.0, tk.END)
        for line in result_lines:
            self.result_text.insert(tk.END, line + "\n")
        self.calculate_btn.config(state="normal")
    
    def show_error(self, error_msg: str) -> None:
        """显示错误信息"""
        self.result_text.delete(1.0, tk.END)
        self.result_text.insert(tk.END, f"错误: {error_msg}")
        self.calculate_btn.config(state="normal")
    
    def clear_results(self) -> None:
        """清空结果"""
        self.result_text.delete(1.0, tk.END)

def main():
    """主函数"""
    root = tk.Tk()
    app = DCACalculatorGUI(root)
    
    # 设置窗口图标（如果有的话）
    try:
        # 可以在这里设置应用程序图标
        pass
    except:
        pass
    
    # 启动GUI
    root.mainloop()

if __name__ == "__main__":
    main()
