#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
定投收益计算器启动脚本
"""

import sys
import os

def check_dependencies():
    """检查依赖项"""
    try:
        import tkinter
        import requests
        return True
    except ImportError as e:
        print(f"缺少依赖项: {e}")
        print("请运行: pip install -r requirements.txt")
        return False

def main():
    """主函数"""
    print("定投收益计算器")
    print("=" * 30)
    
    # 检查依赖项
    if not check_dependencies():
        input("按回车键退出...")
        return
    
    # 导入并启动GUI
    try:
        from dca_gui import main as gui_main
        gui_main()
    except Exception as e:
        print(f"启动GUI失败: {e}")
        input("按回车键退出...")

if __name__ == "__main__":
    main()
