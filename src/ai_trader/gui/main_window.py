"""
主窗口GUI

重构后的主窗口，使用模块化架构，支持多页面切换。
"""

import tkinter as tk
from tkinter import ttk
from typing import Optional, Dict

from .pages import DCAPage
from .pages.technical_analysis_page import TechnicalAnalysisPage


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
        self.root.geometry("1200x800")
        self.root.resizable(True, True)
        
        # 设置样式
        self.setup_styles()
        
        # 初始化变量
        self.current_page: Optional[ttk.Frame] = None
        self.pages: Dict[str, ttk.Frame] = {}
        self.current_page_name: Optional[str] = None
        
        # 创建GUI组件
        self.create_widgets()
        
        # 加载默认页面
        self.load_default_page()
    
    def setup_styles(self) -> None:
        """设置GUI样式"""
        style = ttk.Style()
        style.theme_use('clam')
        
        # 配置样式
        style.configure('Title.TLabel', font=('Arial', 16, 'bold'))
        style.configure('Header.TLabel', font=('Arial', 12, 'bold'))
        style.configure('Info.TLabel', font=('Arial', 10))
        
        # 导航栏样式
        style.configure('Navbar.TFrame', relief='flat', borderwidth=1)
        style.configure('NavbarTitle.TLabel', font=('Arial', 16, 'bold'))
        style.configure('Navbar.TButton', font=('Arial', 10), padding=(10, 5))
        
        # 内容区域样式
        style.configure('Content.TFrame', relief='flat')
    
    def create_widgets(self) -> None:
        """创建GUI组件"""
        # 主框架
        main_frame = ttk.Frame(self.root)
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 配置网格权重
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(1, weight=1)
        
        # 创建顶部导航栏
        self.create_top_navbar(main_frame)
        
        # 创建内容区域
        self.create_content_area(main_frame)
    
    def create_top_navbar(self, parent: ttk.Frame) -> None:
        """创建顶部导航栏"""
        # 顶部导航栏容器
        navbar = ttk.Frame(parent, style='Navbar.TFrame')
        navbar.grid(row=0, column=0, sticky=(tk.W, tk.E), padx=0, pady=0)
        
        # 左侧标题区域
        title_frame = ttk.Frame(navbar)
        title_frame.pack(side=tk.LEFT, padx=20, pady=10)
        
        # 应用标题
        title_label = ttk.Label(title_frame, text="AI数字货币量化交易系统", 
                               style='NavbarTitle.TLabel')
        title_label.pack(side=tk.LEFT)
        
        # 右侧导航按钮区域
        nav_frame = ttk.Frame(navbar)
        nav_frame.pack(side=tk.RIGHT, padx=20, pady=10)
        
        # 导航按钮列表
        nav_buttons = [
            ("定投计算", "dca"),
            ("技术分析", "technical"),
            ("策略管理", "strategy"),
            ("回测分析", "backtest"),
            ("监控面板", "monitoring"),
            ("设置", "settings")
        ]
        
        # 创建导航按钮
        self.nav_buttons = {}
        for i, (text, page_name) in enumerate(nav_buttons):
            btn = ttk.Button(nav_frame, text=text, 
                           command=lambda p=page_name: self.show_page(p),
                           style='Navbar.TButton')
            btn.pack(side=tk.LEFT, padx=5)
            self.nav_buttons[page_name] = btn
    
    
    def create_content_area(self, parent: ttk.Frame) -> None:
        """创建内容区域"""
        # 内容区域
        self.content_frame = ttk.Frame(parent, style='Content.TFrame')
        self.content_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=0, pady=0)
        
        # 配置内容区域自适应
        self.content_frame.columnconfigure(0, weight=1)
        self.content_frame.rowconfigure(0, weight=1)
    
    def load_default_page(self) -> None:
        """加载默认页面"""
        self.show_page("dca")
    
    def show_page(self, page_name: str) -> None:
        """显示指定页面"""
        # 性能优化：如果当前页面就是目标页面，直接返回
        if self.current_page_name == page_name:
            return
        
        # 隐藏当前页面
        if self.current_page:
            self.current_page.grid_remove()
        
        # 如果页面已存在，直接显示
        if page_name in self.pages:
            self.current_page = self.pages[page_name]
            self.current_page.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
            self.current_page_name = page_name
            return
        
        # 创建新页面
        if page_name == "dca":
            self.create_dca_page()
        elif page_name == "technical":
            self.create_technical_page()
        elif page_name == "strategy":
            self.create_strategy_page()
        elif page_name == "backtest":
            self.create_backtest_page()
        elif page_name == "monitoring":
            self.create_monitoring_page()
        elif page_name == "settings":
            self.create_settings_page()
        else:
            self.create_placeholder_page(page_name)
        
        # 更新当前页面名称
        self.current_page_name = page_name
    
    def get_current_page_name(self) -> Optional[str]:
        """获取当前页面名称"""
        return self.current_page_name
    
    def create_dca_page(self) -> None:
        """创建定投计算页面"""
        page_frame = ttk.Frame(self.content_frame, style='Content.TFrame')
        page_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 配置页面自适应
        page_frame.columnconfigure(0, weight=1)
        page_frame.rowconfigure(0, weight=1)
        
        # 创建定投页面实例
        dca_page = DCAPage(page_frame)
        self.pages["dca"] = page_frame
        self.current_page = page_frame
        self.current_page_name = "dca"
    
    def create_technical_page(self) -> None:
        """创建技术分析页面"""
        page_frame = ttk.Frame(self.content_frame, style='Content.TFrame')
        page_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 配置页面自适应
        page_frame.columnconfigure(0, weight=1)
        page_frame.rowconfigure(0, weight=1)
        
        # 创建技术分析页面实例
        technical_page = TechnicalAnalysisPage(page_frame)
        self.pages["technical"] = page_frame
        self.current_page = page_frame
        self.current_page_name = "technical"
    
    def create_strategy_page(self) -> None:
        """创建策略管理页面"""
        page_frame = ttk.Frame(self.content_frame, style='Content.TFrame')
        page_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 占位内容
        ttk.Label(page_frame, text="策略管理功能开发中...", 
                 style='Header.TLabel').pack(expand=True)
        
        self.pages["strategy"] = page_frame
        self.current_page = page_frame
        self.current_page_name = "strategy"
    
    def create_backtest_page(self) -> None:
        """创建回测分析页面"""
        page_frame = ttk.Frame(self.content_frame, style='Content.TFrame')
        page_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 占位内容
        ttk.Label(page_frame, text="回测分析功能开发中...", 
                 style='Header.TLabel').pack(expand=True)
        
        self.pages["backtest"] = page_frame
        self.current_page = page_frame
        self.current_page_name = "backtest"
    
    def create_monitoring_page(self) -> None:
        """创建监控面板页面"""
        page_frame = ttk.Frame(self.content_frame, style='Content.TFrame')
        page_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 占位内容
        ttk.Label(page_frame, text="监控面板功能开发中...", 
                 style='Header.TLabel').pack(expand=True)
        
        self.pages["monitoring"] = page_frame
        self.current_page = page_frame
        self.current_page_name = "monitoring"
    
    def create_settings_page(self) -> None:
        """创建设置页面"""
        page_frame = ttk.Frame(self.content_frame, style='Content.TFrame')
        page_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 占位内容
        ttk.Label(page_frame, text="设置功能开发中...", 
                 style='Header.TLabel').pack(expand=True)
        
        self.pages["settings"] = page_frame
        self.current_page = page_frame
        self.current_page_name = "settings"
    
    def create_placeholder_page(self, page_name: str) -> None:
        """创建占位页面"""
        page_frame = ttk.Frame(self.content_frame, style='Content.TFrame')
        page_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 占位内容
        ttk.Label(page_frame, text=f"{page_name} 功能开发中...", 
                 style='Header.TLabel').pack(expand=True)
        
        self.pages[page_name] = page_frame
        self.current_page = page_frame
        self.current_page_name = page_name


def main():
    """主函数"""
    root = tk.Tk()
    app = MainWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
