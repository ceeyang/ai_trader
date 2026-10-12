import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { api, ApiError } from "../api/client";
import { Providers } from "../test-utils";
import { DcaPage } from "./DcaPage";

const RESULT = {
  symbol: "BTCUSDT",
  total_invested: 400,
  total_coins: 0.01,
  current_price: 50000,
  total_value: 500,
  profit: 100,
  profit_rate: 25,
  average_cost: 40000,
  investment_count: 2,
  records: [{ date: "2024-01-10", price: 40000, amount: 200, coins: 0.005 }],
};

describe("DcaPage", () => {
  it("renders summary after calculate", async () => {
    vi.spyOn(api, "getSymbols").mockResolvedValue({ symbols: ["BTCUSDT"] });
    const calc = vi.spyOn(api, "calculateDca").mockResolvedValue(RESULT);
    render(
      <Providers>
        <DcaPage />
      </Providers>,
    );
    await userEvent.click(await screen.findByRole("button", { name: "计算收益" }));
    expect(await screen.findByText("25.00%")).toBeInTheDocument();
    expect(screen.getByText("2024-01-10")).toBeInTheDocument();
    expect(calc.mock.calls[0][0]).toMatchObject({ symbol: "BTCUSDT", amount: 200, day: 10 });
  });

  it("shows error detail when the API fails", async () => {
    vi.spyOn(api, "getSymbols").mockResolvedValue({ symbols: ["BTCUSDT"] });
    vi.spyOn(api, "calculateDca").mockRejectedValue(new ApiError(502, "binance unreachable"));
    render(
      <Providers>
        <DcaPage />
      </Providers>,
    );
    await userEvent.click(await screen.findByRole("button", { name: "计算收益" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("binance unreachable");
  });
});
