import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { api, ApiError } from "../api/client";
import { DEFAULT_PRESET } from "../api/types";
import { Providers } from "../test-utils";

vi.mock("../components/analysis/PriceChart", () => ({ PriceChart: () => <div data-testid="chart" /> }));
import { AnalysisPage } from "./AnalysisPage";

const BARS = [{ time: 1700000000, open: 1, high: 2, low: 0.5, close: 1.5, volume: 10 }];

function mockBasics() {
  vi.spyOn(api, "getSymbols").mockResolvedValue({ symbols: ["BTCUSDT"] });
  vi.spyOn(api, "getIntervals").mockResolvedValue({ intervals: ["1d"] });
  vi.spyOn(api, "getPreset").mockResolvedValue(DEFAULT_PRESET);
}

describe("AnalysisPage", () => {
  it("shows 502 detail when klines fail", async () => {
    mockBasics();
    vi.spyOn(api, "getKlines").mockRejectedValue(new ApiError(502, "binance unreachable"));
    render(
      <Providers>
        <AnalysisPage />
      </Providers>,
    );
    await userEvent.click(await screen.findByRole("button", { name: "加载数据" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("binance unreachable");
  });

  it("runs analysis then backtest and fills the result tabs", async () => {
    mockBasics();
    vi.spyOn(api, "getKlines").mockResolvedValue({ bars: BARS });
    vi.spyOn(api, "runAnalysis").mockResolvedValue({
      indicators: { rsi: [50] },
      patterns: { hammer: [] },
      entry_signals: [1700000000],
      exit_signals: [],
      effectiveness: { macd_bullish: { frequency: 0.1, avg_price_change_1d: 0.01, positive_rate: 0.6 } },
    });
    vi.spyOn(api, "runBacktest").mockResolvedValue({
      total_trades: 1, winning_trades: 1, losing_trades: 0, win_rate: 1, total_pnl: 10, total_return: 0.1,
      max_drawdown: 0.02, sharpe_ratio: 1.5, avg_trade_duration: 3,
      trades: [{ entry_time: 1700000000, exit_time: 1700086400, entry_price: 1, exit_price: 2, quantity: 1, pnl: 1, pnl_percent: 1, duration: 1, signal_strength: 0.5 }],
    });
    render(
      <Providers>
        <AnalysisPage />
      </Providers>,
    );
    await userEvent.click(await screen.findByRole("button", { name: "加载数据" }));
    await userEvent.click(await screen.findByRole("button", { name: "开始分析" }));
    expect(await screen.findByText("macd_bullish")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "运行回测" }));
    await userEvent.click(await screen.findByRole("tab", { name: "回测结果" }));
    expect(await screen.findByText("总交易次数")).toBeInTheDocument();
  });
});
