#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI数字货币量化交易系统安装脚本
"""

from setuptools import setup, find_packages

# 读取README文件
with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

# 读取requirements文件
with open("requirements.txt", "r", encoding="utf-8") as fh:
    requirements = [line.strip() for line in fh if line.strip() and not line.startswith("#")]

setup(
    name="ai-trader",
    version="0.1.0",
    author="CeeYang",
    author_email="ceeyang2024@gmail.com",
    description="AI数字货币量化交易系统",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/ai-trader/ai-trader",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Financial and Insurance Industry",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Office/Business :: Financial :: Investment",
    ],
    python_requires=">=3.8",
    install_requires=requirements,
    extras_require={
        "dev": [
            "pytest>=6.0.0",
            "pytest-cov>=2.12.0",
            "black>=21.0.0",
            "flake8>=3.9.0",
            "mypy>=0.910",
            "pre-commit>=2.15.0",
        ],
        "ml": [
            "scikit-learn>=1.0.0",
            "tensorflow>=2.8.0",
            "torch>=1.11.0",
        ],
        "database": [
            "psycopg2-binary>=2.9.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "ai-trader=ai_trader.cli:main",
            "ai-trader-gui=ai_trader.gui.main_window:main",
        ],
    },
    include_package_data=True,
    zip_safe=False,
)
