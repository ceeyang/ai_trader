"""
命令行接口

提供命令行工具来执行各种操作。
"""

import argparse
import sys
from datetime import datetime
from typing import Optional

from .strategies.dca.dca_strategy import DCAStrategy


def main() -> None:
    """主CLI函数"""
    parser = argparse.ArgumentParser(description="AI数字货币量化交易系统")
    subparsers = parser.add_subparsers(dest='command', help='可用命令')
    
    # 定投计算命令
    dca_parser = subparsers.add_parser('dca', help='定投收益计算')
    dca_parser.add_argument('--symbol', required=True, help='交易对符号')
    dca_parser.add_argument('--amount', type=float, required=True, help='定投金额')
    dca_parser.add_argument('--day', type=int, required=True, help='定投日期')
    dca_parser.add_argument('--start-date', required=True, help='开始日期 (YYYY-MM-DD)')
    dca_parser.add_argument('--end-date', help='结束日期 (YYYY-MM-DD)')
    
    # 策略管理命令
    strategy_parser = subparsers.add_parser('strategy', help='策略管理')
    strategy_parser.add_argument('--list', action='store_true', help='列出可用策略')
    strategy_parser.add_argument('--run', help='运行指定策略')
    
    # 回测命令
    backtest_parser = subparsers.add_parser('backtest', help='策略回测')
    backtest_parser.add_argument('--strategy', required=True, help='策略名称')
    backtest_parser.add_argument('--start-date', required=True, help='开始日期')
    backtest_parser.add_argument('--end-date', required=True, help='结束日期')
    backtest_parser.add_argument('--initial-capital', type=float, default=10000, help='初始资金')
    
    args = parser.parse_args()
    
    if args.command == 'dca':
        run_dca_calculation(args)
    elif args.command == 'strategy':
        run_strategy_management(args)
    elif args.command == 'backtest':
        run_backtest(args)
    else:
        parser.print_help()


def run_dca_calculation(args) -> None:
    """运行定投计算"""
    try:
        # 解析日期
        start_date = datetime.strptime(args.start_date, "%Y-%m-%d")
        end_date = datetime.strptime(args.end_date, "%Y-%m-%d") if args.end_date else datetime.now()
        
        # 创建定投策略
        dca_strategy = DCAStrategy(
            symbol=args.symbol,
            invest_amount=args.amount,
            invest_day=args.day,
            start_date=start_date,
            end_date=end_date
        )
        
        # 执行计算
        result = dca_strategy.execute_dca()
        
        # 输出结果
        print(f"\n定投收益计算结果")
        print("=" * 50)
        print(f"币种: {result['symbol']}")
        print(f"定投金额: {args.amount} USDT")
        print(f"定投日期: 每月{args.day}号")
        print(f"时间范围: {start_date.strftime('%Y-%m-%d')} 至 {end_date.strftime('%Y-%m-%d')}")
        print(f"投资次数: {result['investment_count']}")
        print("-" * 50)
        print("定投详情:")
        
        for record in result['records']:
            print(f"{record['date']}: 价格={record['price']:.2f} USDT, "
                  f"买入={record['coins']:.6f} {args.symbol}")
        
        print("\n" + "=" * 50)
        print("收益汇总:")
        print(f"当前价格: {result['current_price']:.2f} USDT")
        print(f"总投入: {result['total_invested']:.2f} USDT")
        print(f"当前总价值: {result['total_value']:.2f} USDT")
        print(f"收益: {result['profit']:.2f} USDT")
        print(f"收益率: {result['profit_rate']:.2f}%")
        print(f"累计买入: {result['total_coins']:.6f} {args.symbol}")
        print(f"平均成本: {result['average_cost']:.2f} USDT")
        print("=" * 50)
        
    except Exception as e:
        print(f"计算失败: {str(e)}", file=sys.stderr)
        sys.exit(1)


def run_strategy_management(args) -> None:
    """运行策略管理"""
    if args.list:
        print("可用策略:")
        print("- DCA (定投策略)")
        print("- SMA (简单移动平均策略)")
        print("- RSI (相对强弱指数策略)")
        print("- Bollinger (布林带策略)")
    elif args.run:
        print(f"运行策略: {args.run}")
        print("策略运行功能开发中...")


def run_backtest(args) -> None:
    """运行回测"""
    print(f"回测策略: {args.strategy}")
    print(f"时间范围: {args.start_date} 至 {args.end_date}")
    print(f"初始资金: {args.initial_capital}")
    print("回测功能开发中...")


if __name__ == "__main__":
    main()
