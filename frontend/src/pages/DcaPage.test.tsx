import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { api, ApiError } from "../api/client";
import type { DCAResponse } from "../api/types";
import { Providers } from "../test-utils";
import { DcaPage } from "./DcaPage";

const LEG = {
  symbol: "BTCUSDT", weight: 1, total_invested: 400, total_coins: 0.01, current_price: 50000, total_value: 500,
  profit: 100, profit_rate: 25, average_cost: 40000, investment_count: 2,
  records: [{ date: "2024-01-10", price: 40000, amount: 200, coins: 0.005 }, { date: "2024-02-10", price: 40000, amount: 200, coins: 0.005 }],
};
const RESULT: DCAResponse = {
  frequency: "monthly", amount: 200, start_date: "2024-01-01", end_date: "2024-03-31", investment_count: 2,
  total_invested: 400, total_value: 500, profit: 100, profit_rate: 25, legs: [LEG],
  records: [{ date: "2024-01-10", amount: 200 }, { date: "2024-02-10", amount: 200 }],
  symbol: "BTCUSDT", total_coins: 0.01, current_price: 50000, average_cost: 40000,
};

function setup() {
  vi.spyOn(api, "getSymbols").mockResolvedValue({ symbols: ["BTCUSDT", "ETHUSDT"] });
  const calc = vi.spyOn(api, "calculateDca").mockResolvedValue(RESULT);
  render(<Providers><DcaPage /></Providers>);
  return calc;
}

describe("DcaPage", () => {
  it("sends a monthly single-symbol plan by default and renders the summary", async () => {
    const calc = setup();
    await userEvent.click(await screen.findByRole("button", { name: "计算收益" }));
    expect(await screen.findByText("25.00%")).toBeInTheDocument();
    expect(screen.getByText("2024-01-10")).toBeInTheDocument();
    expect(calc.mock.calls[0][0]).toMatchObject({ frequency: "monthly", day: 10, amount: 200, allocations: [{ symbol: "BTCUSDT", weight: 1 }] });
  });

  it("daily frequency hides the day-of-month field and is sent", async () => {
    const calc = setup();
    await userEvent.click(await screen.findByLabelText("每日"));
    expect(screen.queryByLabelText("每月定投日")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "计算收益" }));
    expect(calc.mock.calls[0][0]).toMatchObject({ frequency: "daily" });
  });

  it("adding a second symbol sends a weighted portfolio", async () => {
    const calc = setup();
    await screen.findByRole("button", { name: "计算收益" });
    await userEvent.click(screen.getByRole("button", { name: "添加币种" }));
    const rows = screen.getAllByTestId("allocation-row");
    expect(rows).toHaveLength(2);
    await userEvent.selectOptions(within(rows[1]).getByRole("combobox"), "ETHUSDT");
    const w = within(rows[1]).getByRole("spinbutton", { name: "权重" });
    await userEvent.clear(w);
    await userEvent.type(w, "40");
    const w0 = within(rows[0]).getByRole("spinbutton", { name: "权重" });
    await userEvent.clear(w0);
    await userEvent.type(w0, "60");
    expect(within(rows[0]).getByText("60.0%")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "计算收益" }));
    expect(calc.mock.calls[0][0]).toMatchObject({ allocations: [{ symbol: "BTCUSDT", weight: 60 }, { symbol: "ETHUSDT", weight: 40 }] });
  });

  it("shows error detail when the API fails", async () => {
    vi.spyOn(api, "getSymbols").mockResolvedValue({ symbols: ["BTCUSDT"] });
    vi.spyOn(api, "calculateDca").mockRejectedValue(new ApiError(502, "binance unreachable"));
    render(<Providers><DcaPage /></Providers>);
    await userEvent.click(await screen.findByRole("button", { name: "计算收益" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("binance unreachable");
  });
});
