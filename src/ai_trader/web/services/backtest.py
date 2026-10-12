"""回测编排：自定义信号 + BacktestEngine → JSON。"""

import math
from typing import Optional

from ai_trader.core.analysis.backtest import BacktestEngine, BacktestResult
from ai_trader.core.analysis.signals import SignalDetector
from ai_trader.web.schemas import BacktestRequest, BacktestResponse, TradeOut
from ai_trader.web.services.market_data import fetch_klines, to_unix_seconds


def _num(value: object) -> Optional[float]:
    f = float(value)  # type: ignore[arg-type]
    return None if math.isnan(f) or math.isinf(f) else f


def _to_response(result: BacktestResult) -> BacktestResponse:
    return BacktestResponse(
        total_trades=int(result.total_trades),
        winning_trades=int(result.winning_trades),
        losing_trades=int(result.losing_trades),
        win_rate=_num(result.win_rate),
        total_pnl=_num(result.total_pnl) or 0.0,
        total_return=_num(result.total_return) or 0.0,
        max_drawdown=_num(result.max_drawdown) or 0.0,
        sharpe_ratio=_num(result.sharpe_ratio),
        avg_trade_duration=_num(result.avg_trade_duration),
        trades=[
            TradeOut(
                entry_time=to_unix_seconds(t.entry_time),
                exit_time=to_unix_seconds(t.exit_time),
                entry_price=float(t.entry_price),
                exit_price=float(t.exit_price),
                quantity=float(t.quantity),
                pnl=float(t.pnl),
                pnl_percent=float(t.pnl_percent),
                duration=int(t.duration),
                signal_strength=_num(t.signal_strength) or 0.0,
            )
            for t in result.trades
        ],
    )


def run_backtest(req: BacktestRequest) -> BacktestResponse:
    d = req.data
    df = fetch_klines(d.symbol, d.interval, d.start.isoformat(), d.end.isoformat())
    engine = BacktestEngine(df, req.backtest.initial_capital)
    engine.commission_rate = req.backtest.commission_rate
    engine.slippage_rate = req.backtest.slippage_rate
    config = req.signals.to_config()
    detector = SignalDetector(df)
    result = engine.run_backtest(
        entry_signals=detector.get_custom_entry_signals(config),
        exit_signals=detector.get_custom_exit_signals(config),
        position_size=req.backtest.position_size,
    )
    return _to_response(result)
