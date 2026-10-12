// 与后端 src/ai_trader/web/schemas.py 逐字段对应

export interface Bar {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}
export interface KlinesResponse {
  bars: Bar[];
}
export interface SymbolsResponse {
  symbols: string[];
}
export interface IntervalsResponse {
  intervals: string[];
}

export interface DCARequest {
  symbol: string;
  amount: number;
  day: number;
  start_date: string;
  end_date: string | null;
}
export interface DCARecord {
  date: string;
  price: number;
  amount: number;
  coins: number;
}
export interface DCAResponse {
  symbol: string;
  total_invested: number;
  total_coins: number;
  current_price: number;
  total_value: number;
  profit: number;
  profit_rate: number;
  average_cost: number;
  investment_count: number;
  records: DCARecord[];
}

export interface IndicatorParams {
  sma_periods: number[];
  macd_fast: number;
  macd_slow: number;
  macd_signal: number;
  rsi_period: number;
  kdj_k: number;
  kdj_d: number;
  kdj_j: number;
  bb_period: number;
  bb_std: number;
}
export interface SignalParams {
  rsi_oversold: number;
  rsi_overbought: number;
  trend_required: boolean;
  macd_required: boolean;
  rsi_required: boolean;
  kdj_required: boolean;
  bb_required: boolean;
  pattern_required: boolean;
  volume_required: boolean;
  combination: "all" | "min";
  min_conditions: number;
}
export interface DataRange {
  symbol: string;
  interval: string;
  start: string;
  end: string;
}
export interface AnalysisRequest {
  data: DataRange;
  indicators: IndicatorParams;
  signals: SignalParams;
}
export interface EffectivenessStat {
  frequency: number;
  avg_price_change_1d: number;
  positive_rate: number;
}
export interface AnalysisResponse {
  indicators: Record<string, (number | null)[]>;
  patterns: Record<string, number[]>;
  entry_signals: number[];
  exit_signals: number[];
  effectiveness: Record<string, EffectivenessStat>;
}

export interface BacktestParams {
  initial_capital: number;
  position_size: number;
  commission_rate: number;
  slippage_rate: number;
}
export interface BacktestRequest extends AnalysisRequest {
  backtest: BacktestParams;
}
export interface TradeOut {
  entry_time: number;
  exit_time: number;
  entry_price: number;
  exit_price: number;
  quantity: number;
  pnl: number;
  pnl_percent: number;
  duration: number;
  signal_strength: number;
}
export interface BacktestResponse {
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number | null;
  total_pnl: number;
  total_return: number;
  max_drawdown: number;
  sharpe_ratio: number | null;
  avg_trade_duration: number | null;
  trades: TradeOut[];
}

export interface AnalysisPreset {
  indicators: IndicatorParams;
  signals: SignalParams;
  backtest: BacktestParams;
}

export const DEFAULT_INDICATORS: IndicatorParams = {
  sma_periods: [5, 10, 20, 50, 200],
  macd_fast: 12,
  macd_slow: 26,
  macd_signal: 9,
  rsi_period: 14,
  kdj_k: 9,
  kdj_d: 3,
  kdj_j: 3,
  bb_period: 20,
  bb_std: 2.0,
};
export const DEFAULT_SIGNALS: SignalParams = {
  rsi_oversold: 30,
  rsi_overbought: 70,
  trend_required: true,
  macd_required: true,
  rsi_required: true,
  kdj_required: true,
  bb_required: true,
  pattern_required: true,
  volume_required: true,
  combination: "all",
  min_conditions: 2,
};
export const DEFAULT_BACKTEST: BacktestParams = {
  initial_capital: 100000,
  position_size: 0.1,
  commission_rate: 0.001,
  slippage_rate: 0.0005,
};
export const DEFAULT_PRESET: AnalysisPreset = {
  indicators: DEFAULT_INDICATORS,
  signals: DEFAULT_SIGNALS,
  backtest: DEFAULT_BACKTEST,
};
