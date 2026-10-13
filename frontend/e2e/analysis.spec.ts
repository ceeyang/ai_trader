import { expect, test, type Page } from "@playwright/test";
import analysis from "./fixtures/analysis.json" with { type: "json" };
import backtest from "./fixtures/backtest.json" with { type: "json" };
import intervals from "./fixtures/intervals.json" with { type: "json" };
import klines from "./fixtures/klines.json" with { type: "json" };
import preset from "./fixtures/preset.json" with { type: "json" };
import symbols from "./fixtures/symbols.json" with { type: "json" };

async function mockApi(page: Page) {
  await page.route("**/api/market/symbols*", (r) => r.fulfill({ json: symbols }));
  await page.route("**/api/market/intervals", (r) => r.fulfill({ json: intervals }));
  await page.route("**/api/config/analysis", (r) => r.fulfill({ json: preset }));
  await page.route("**/api/market/klines*", (r) => r.fulfill({ json: klines }));
  await page.route("**/api/analysis/run", (r) => r.fulfill({ json: analysis }));
  await page.route("**/api/backtest/run", (r) => r.fulfill({ json: backtest }));
}

test("load → analyze → backtest", async ({ page }) => {
  await mockApi(page);
  await page.goto("/analysis");
  await page.getByRole("button", { name: "加载数据" }).click();
  await expect(page.getByText("已加载 30 根K线")).toBeVisible();
  await expect(page.getByTestId("price-chart").locator("canvas").first()).toBeVisible();
  await page.getByRole("button", { name: "开始分析" }).click();
  await expect(page.getByRole("tab", { name: "分析结果" })).toBeVisible();
  await expect(page.getByText("macd_bullish")).toBeVisible();
  await page.getByRole("button", { name: "运行回测" }).click();
  await page.getByRole("tab", { name: "回测结果" }).click();
  await expect(page.getByText("总交易次数")).toBeVisible();
  await expect(page.getByText("320.50", { exact: true })).toBeVisible();
});

test("shows error when backend is down", async ({ page }) => {
  await mockApi(page);
  await page.route("**/api/market/klines*", (r) => r.fulfill({ status: 502, json: { detail: "binance unreachable" } }));
  await page.goto("/analysis");
  await page.getByRole("button", { name: "加载数据" }).click();
  await expect(page.getByRole("alert")).toHaveText("binance unreachable");
});

test("dca page calculates", async ({ page }) => {
  await mockApi(page);
  await page.route("**/api/dca/calculate", (r) =>
    r.fulfill({
      json: {
        frequency: "monthly", amount: 200, start_date: "2024-01-01", end_date: "2024-03-31", investment_count: 2,
        total_invested: 400, total_value: 500, profit: 100, profit_rate: 25,
        legs: [{ symbol: "BTCUSDT", weight: 1, total_invested: 400, total_coins: 0.01, current_price: 50000, total_value: 500, profit: 100, profit_rate: 25, average_cost: 40000, investment_count: 2,
          records: [{ date: "2024-01-10", price: 40000, amount: 200, coins: 0.005 }, { date: "2024-02-10", price: 40000, amount: 200, coins: 0.005 }] }],
        records: [{ date: "2024-01-10", amount: 200 }, { date: "2024-02-10", amount: 200 }],
        symbol: "BTCUSDT", total_coins: 0.01, current_price: 50000, average_cost: 40000,
      },
    }),
  );
  await page.goto("/dca");
  await page.getByRole("button", { name: "计算收益" }).click();
  await expect(page.getByText("25.00%")).toBeVisible();
});
