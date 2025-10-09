"""
主窗口GUI

重构后的主窗口，使用新的模块化架构。
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from ..strategies.dca.dca_strategy import DCAStrategy
from ..core.data.providers import BinanceDataSource


class MainWindow:
    """主窗口类"""
    
    def __init__(self, root: tk.Tk) -> None:
        """
        初始化主窗口
        
        Args:
            root: tkinter根窗口
        """
        self.root = root
        self.root.title("AI数字货币量化交易系统")
        self.root.geometry("1000x800")
        self.root.resizable(True, True)
        
        # 设置样式
        self.setup_styles()
        
        # 初始化变量
        self.symbols_list: List[str] = []
        self.data_source: Optional[BinanceDataSource] = None
        
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
        title_label = ttk.Label(main_frame, text="AI数字货币量化交易系统", style='Title.TLabel')
        title_label.grid(row=0, column=0, columnspan=2, pady=(0, 20))
        
        # 创建选项卡
        self.notebook = ttk.Notebook(main_frame)
        self.notebook.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), pady=10)
        
        # 定投计算选项卡
        self.create_dca_tab()
        
        # 策略管理选项卡
        self.create_strategy_tab()
        
        # 监控面板选项卡
        self.create_monitoring_tab()
        
        # 配置网格权重
        main_frame.rowconfigure(1, weight=1)
    
    def create_dca_tab(self) -> None:
        """创建定投计算选项卡"""
        dca_frame = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(dca_frame, text="定投计算")
        
        # 配置网格
        dca_frame.columnconfigure(1, weight=1)
        
        # 币种选择
        ttk.Label(dca_frame, text="选择币种:", style='Header.TLabel').grid(row=0, column=0, sticky=tk.W, pady=5)
        self.symbol_var = tk.StringVar(value="SOLUSDT")
        self.symbol_combo = ttk.Combobox(dca_frame, textvariable=self.symbol_var, width=20, state="readonly")
        self.symbol_combo.grid(row=0, column=1, sticky=(tk.W, tk.E), pady=5, padx=(10, 0))
        
        # 开始日期选择
        ttk.Label(dca_frame, text="开始日期:", style='Header.TLabel').grid(row=1, column=0, sticky=tk.W, pady=5)
        self.start_date_var = tk.StringVar(value="2024-01-01")
        self.start_date_entry = ttk.Entry(dca_frame, textvariable=self.start_date_var, width=20)
        self.start_date_entry.grid(row=1, column=1, sticky=(tk.W, tk.E), pady=5, padx=(10, 0))
        
        # 结束日期选择
        ttk.Label(dca_frame, text="结束日期:", style='Header.TLabel').grid(row=2, column=0, sticky=tk.W, pady=5)
        self.end_date_var = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d"))
        self.end_date_entry = ttk.Entry(dca_frame, textvariable=self.end_date_var, width=20)
        self.end_date_entry.grid(row=2, column=1, sticky=(tk.W, tk.E), pady=5, padx=(10, 0))
        
        # 定投日期选择
        ttk.Label(dca_frame, text="定投日期:", style='Header.TLabel').grid(row=3, column=0, sticky=tk.W, pady=5)
        self.invest_day_var = tk.StringVar(value="10")
        self.invest_day_combo = ttk.Combobox(dca_frame, textvariable=self.invest_day_var, 
                                           values=[str(i) for i in range(1, 32)], width=20, state="readonly")
        self.invest_day_combo.grid(row=3, column=1, sticky=(tk.W, tk.E), pady=5, padx=(10, 0))
        
        # 定投金额
        ttk.Label(dca_frame, text="定投金额 (USDT):", style='Header.TLabel').grid(row=4, column=0, sticky=tk.W, pady=5)
        self.invest_amount_var = tk.StringVar(value="200")
        self.invest_amount_entry = ttk.Entry(dca_frame, textvariable=self.invest_amount_var, width=20)
        self.invest_amount_entry.grid(row=4, column=1, sticky=(tk.W, tk.E), pady=5, padx=(10, 0))
        
        # 按钮框架
        button_frame = ttk.Frame(dca_frame)
        button_frame.grid(row=5, column=0, columnspan=2, pady=20)
        
        # 计算按钮
        self.calculate_btn = ttk.Button(button_frame, text="计算收益", command=self.calculate_dca_profit)
        self.calculate_btn.pack(side=tk.LEFT, padx=5)
        
        # 清空按钮
        self.clear_btn = ttk.Button(button_frame, text="清空结果", command=self.clear_results)
        self.clear_btn.pack(side=tk.LEFT, padx=5)
        
        # 结果显示区域
        ttk.Label(dca_frame, text="计算结果:", style='Header.TLabel').grid(row=6, column=0, sticky=tk.W, pady=(20, 5))
        
        # 创建结果显示的文本框
        self.result_text = scrolledtext.ScrolledText(dca_frame, height=15, width=80, wrap=tk.WORD)
        self.result_text.grid(row=7, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        
        # 配置网格权重
        dca_frame.rowconfigure(7, weight=1)
    
    def create_strategy_tab(self) -> None:
        """创建策略管理选项卡"""
        strategy_frame = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(strategy_frame, text="策略管理")
        
        ttk.Label(strategy_frame, text="策略管理功能开发中...", style='Info.TLabel').pack(pady=50)
    
    def create_monitoring_tab(self) -> None:
        """创建监控面板选项卡"""
        monitoring_frame = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(monitoring_frame, text="监控面板")
        
        ttk.Label(monitoring_frame, text="监控面板功能开发中...", style='Info.TLabel').pack(pady=50)
    
    def load_symbols(self) -> None:
        """加载币种列表"""
        def load_symbols_thread():
            try:
                self.data_source = BinanceDataSource()
                if self.data_source.connect():
                    symbols = self.data_source.get_available_symbols()
                    if symbols:
                        self.symbols_list = symbols
                        self.root.after(0, self.update_symbol_combo)
                    else:
                        # 使用默认币种列表
                        self.symbols_list = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "ADAUSDT"]
                        self.root.after(0, self.update_symbol_combo)
                else:
                    self.symbols_list = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "ADAUSDT"]
                    self.root.after(0, self.update_symbol_combo)
                    
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("错误", f"加载币种列表失败: {str(e)}"))
        
        # 在后台线程中加载币种
        threading.Thread(target=load_symbols_thread, daemon=True).start()
    
    def update_symbol_combo(self) -> None:
        """更新币种下拉框"""
        self.symbol_combo['values'] = self.symbols_list
    
    def calculate_dca_profit(self) -> None:
        """计算定投收益"""
        try:
            # 获取输入参数
            symbol = self.symbol_var.get().strip()
            start_date_str = self.start_date_var.get().strip()
            end_date_str = self.end_date_var.get().strip()
            invest_day = int(self.invest_day_var.get())
            invest_amount = float(self.invest_amount_var.get())
            
            # 验证输入
            if not symbol or not start_date_str or not end_date_str:
                messagebox.showerror("错误", "请填写所有必填字段")
                return
            
            if invest_amount <= 0:
                messagebox.showerror("错误", "定投金额必须大于0")
                return
            
            # 解析日期
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
            
            # 显示计算中状态
            self.result_text.delete(1.0, tk.END)
            self.result_text.insert(tk.END, "正在计算，请稍候...\n")
            self.calculate_btn.config(state="disabled")
            
            # 在后台线程中执行计算
            threading.Thread(target=self.calculate_dca_profit_thread, 
                           args=(symbol, start_date, end_date, invest_day, invest_amount), 
                           daemon=True).start()
            
        except ValueError as e:
            messagebox.showerror("错误", f"输入格式错误: {str(e)}")
        except Exception as e:
            messagebox.showerror("错误", f"计算失败: {str(e)}")
    
    def calculate_dca_profit_thread(self, symbol: str, start_date: datetime, end_date: datetime, 
                                  invest_day: int, invest_amount: float) -> None:
        """在后台线程中计算定投收益"""
        try:
            # 创建定投策略
            dca_strategy = DCAStrategy(
                symbol=symbol,
                invest_amount=invest_amount,
                invest_day=invest_day,
                start_date=start_date,
                end_date=end_date
            )
            
            # 执行定投计算
            result = dca_strategy.execute_dca()
            
            # 格式化结果
            result_lines = []
            result_lines.append(f"币种: {result['symbol']}")
            result_lines.append(f"定投日期: 每月{invest_day}号")
            result_lines.append(f"定投金额: {invest_amount} USDT")
            result_lines.append(f"时间范围: {start_date.strftime('%Y-%m-%d')} 至 {end_date.strftime('%Y-%m-%d')}")
            result_lines.append(f"投资次数: {result['investment_count']}")
            result_lines.append("-" * 50)
            result_lines.append("定投详情:")
            
            for record in result['records']:
                result_lines.append(f"{record['date']}: 价格={record['price']:.2f} USDT, "
                                  f"买入={record['coins']:.6f} {symbol}")
            
            result_lines.append("\n" + "=" * 50)
            result_lines.append("收益汇总:")
            result_lines.append(f"当前价格: {result['current_price']:.2f} USDT")
            result_lines.append(f"总投入: {result['total_invested']:.2f} USDT")
            result_lines.append(f"当前总价值: {result['total_value']:.2f} USDT")
            result_lines.append(f"收益: {result['profit']:.2f} USDT")
            result_lines.append(f"收益率: {result['profit_rate']:.2f}%")
            result_lines.append(f"累计买入: {result['total_coins']:.6f} {symbol}")
            result_lines.append(f"平均成本: {result['average_cost']:.2f} USDT")
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
    app = MainWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
