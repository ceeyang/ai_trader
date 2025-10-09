import requests
from datetime import datetime, timedelta

# ------------------------------
# 配置部分
# ------------------------------
SYMBOL = "SOLUSDT"       # 定投币种
INTERVAL = "1d"          # 日K线
MONTHLY_INVEST = 200      # 每月投入金额 USDT
NUM_MONTHS = 12           # 最近 12 个月
INVEST_DAY = 10           # 每月定投日期（10号）
BINANCE_API = "https://api.binance.com/api/v3/klines"
BINANCE_TICKER_API = "https://api.binance.com/api/v3/ticker/price"

# ------------------------------
# 获取历史K线数据
# ------------------------------
def get_daily_klines(symbol: str, interval: str, limit: int) -> list:
    """
    获取日K线数据
    :param symbol: 交易对符号
    :param interval: 时间间隔
    :param limit: 数据条数
    :return: K线数据列表
    """
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    }
    resp = requests.get(BINANCE_API, params=params)
    data = resp.json()
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

# ------------------------------
# 筛选每月10号的定投数据
# ------------------------------
def filter_investment_dates(klines: list, invest_day: int) -> list:
    """
    筛选出每月指定日期的K线数据用于定投计算
    :param klines: 日K线数据列表
    :param invest_day: 定投日期（每月几号）
    :return: 筛选后的定投数据列表
    """
    investment_data = []
    current_month = None
    
    for kline in klines:
        kline_date = kline['datetime']
        # 如果是新的月份，记录当前月份
        if current_month != kline_date.month:
            current_month = kline_date.month
        
        # 如果是定投日期，添加到投资数据中
        if kline_date.day == invest_day:
            investment_data.append(kline)
    
    return investment_data

# ------------------------------
# 获取当前实时价格
# ------------------------------
def get_current_price(symbol: str) -> float:
    """
    获取指定交易对的当前实时价格
    :param symbol: 交易对符号
    :return: 当前价格
    """
    try:
        params = {"symbol": symbol}
        resp = requests.get(BINANCE_TICKER_API, params=params)
        data = resp.json()
        current_price: float = float(data['price'])
        return current_price
    except Exception as e:
        print(f"获取当前价格失败: {e}")
        return 0.0

# ------------------------------
# 计算定投收益
# ------------------------------
def calculate_dca_profit(investment_data: list, monthly_invest: float) -> None:
    """
    计算每月10号定投的收益情况
    :param investment_data: 定投数据列表
    :param monthly_invest: 每月投资金额
    """
    total_coins: float = 0.0
    total_invested: float = 0.0
    
    print(f"每月{INVEST_DAY}号定投详情：")
    print("-" * 50)
    
    for i, k in enumerate(investment_data):
        coins_bought: float = monthly_invest / k['close']
        total_coins += coins_bought
        total_invested += monthly_invest
        print(f"{k['date']}: 价格={k['close']:.2f} USDT, 买入={coins_bought:.6f} {SYMBOL}")
    
    # 获取当前实时价格
    print("\n正在获取当前实时价格...")
    current_price: float = get_current_price(SYMBOL)
    
    if current_price == 0.0:
        print("无法获取当前价格，使用最后一个定投日期的价格")
        current_price = investment_data[-1]['close']
    
    total_value: float = total_coins * current_price
    profit: float = total_value - total_invested
    profit_rate: float = profit / total_invested * 100
    
    print("\n" + "=" * 50)
    print("定投收益汇总：")
    print(f"当前价格: {current_price:.2f} USDT")
    print(f"总投入: {total_invested:.2f} USDT")
    print(f"当前总价值: {total_value:.2f} USDT")
    print(f"收益: {profit:.2f} USDT")
    print(f"收益率: {profit_rate:.2f}%")
    print(f"累计买入: {total_coins:.6f} {SYMBOL}")
    print(f"平均成本: {total_invested/total_coins:.2f} USDT")
    print("=" * 50)

# ------------------------------
# 主函数
# ------------------------------
def main() -> None:
    """
    主函数：执行每月10号定投收益计算
    """
    print(f"开始计算 {SYMBOL} 每月{INVEST_DAY}号定投收益...")
    print(f"投资金额: {MONTHLY_INVEST} USDT/月")
    print(f"计算周期: 最近 {NUM_MONTHS} 个月")
    print()
    
    # 获取足够多的日K线数据（大约400天，确保覆盖12个月）
    daily_klines = get_daily_klines(SYMBOL, INTERVAL, 400)
    
    # 筛选出每月10号的定投数据
    investment_data = filter_investment_dates(daily_klines, INVEST_DAY)
    
    if not investment_data:
        print("错误：未找到符合条件的定投日期数据！")
        return
    
    print(f"找到 {len(investment_data)} 次定投记录")
    print()
    
    # 计算定投收益
    calculate_dca_profit(investment_data, MONTHLY_INVEST)

if __name__ == "__main__":
    main()
