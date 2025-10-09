#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
项目结构迁移脚本

将旧的项目结构迁移到新的模块化架构。
"""

import os
import shutil
from pathlib import Path


def migrate_project():
    """迁移项目结构"""
    print("开始迁移项目结构...")
    
    # 备份旧文件
    backup_old_files()
    
    # 移动旧文件到新位置
    move_old_files()
    
    # 创建新的启动脚本
    create_new_scripts()
    
    print("项目结构迁移完成！")
    print("\n新的使用方式:")
    print("1. GUI应用: python -m ai_trader.gui.main_window")
    print("2. CLI工具: python -m ai_trader.cli dca --help")
    print("3. 安装开发版本: pip install -e .")


def backup_old_files():
    """备份旧文件"""
    print("备份旧文件...")
    
    old_files = [
        "dca_profit.py",
        "dca_gui.py", 
        "run_gui.py"
    ]
    
    backup_dir = Path("backup")
    backup_dir.mkdir(exist_ok=True)
    
    for file in old_files:
        if os.path.exists(file):
            shutil.copy2(file, backup_dir / file)
            print(f"已备份: {file}")


def move_old_files():
    """移动旧文件到新位置"""
    print("移动旧文件到新位置...")
    
    # 移动旧文件到legacy目录
    legacy_dir = Path("legacy")
    legacy_dir.mkdir(exist_ok=True)
    
    old_files = [
        "dca_profit.py",
        "dca_gui.py",
        "run_gui.py"
    ]
    
    for file in old_files:
        if os.path.exists(file):
            shutil.move(file, legacy_dir / file)
            print(f"已移动: {file} -> legacy/{file}")


def create_new_scripts():
    """创建新的启动脚本"""
    print("创建新的启动脚本...")
    
    # 创建GUI启动脚本
    gui_script = """#!/usr/bin/env python3
# -*- coding: utf-8 -*-
\"\"\"
GUI应用启动脚本
\"\"\"

if __name__ == "__main__":
    from ai_trader.gui.main_window import main
    main()
"""
    
    with open("run_gui_new.py", "w", encoding="utf-8") as f:
        f.write(gui_script)
    
    # 创建CLI启动脚本
    cli_script = """#!/usr/bin/env python3
# -*- coding: utf-8 -*-
\"\"\"
CLI工具启动脚本
\"\"\"

if __name__ == "__main__":
    from ai_trader.cli import main
    main()
"""
    
    with open("run_cli.py", "w", encoding="utf-8") as f:
        f.write(cli_script)
    
    print("已创建新的启动脚本:")
    print("- run_gui_new.py (GUI应用)")
    print("- run_cli.py (CLI工具)")


if __name__ == "__main__":
    migrate_project()
