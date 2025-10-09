#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GUI应用启动脚本 - 简化版本
"""

import sys
import os
from pathlib import Path

# 添加src目录到Python路径
current_dir = Path(__file__).parent
src_dir = current_dir / "src"
sys.path.insert(0, str(src_dir))

# 设置PYTHONPATH环境变量
os.environ['PYTHONPATH'] = str(src_dir)

if __name__ == "__main__":
    try:
        from ai_trader.gui.main_window import main
        main()
    except ImportError as e:
        print(f"导入错误: {e}")
        print("请确保已安装依赖: pip install -r requirements.txt")
        print("并安装开发版本: pip install -e .")
        sys.exit(1)
