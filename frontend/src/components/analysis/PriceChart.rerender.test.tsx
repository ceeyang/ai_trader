import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  createChart: vi.fn(() => ({
    addSeries: vi.fn(() => ({ setData: vi.fn(), priceScale: () => ({ applyOptions: vi.fn() }) })),
    timeScale: () => ({ fitContent: vi.fn() }),
    remove: vi.fn(),
    applyOptions: vi.fn(),
    panes: () => [{ setStretchFactor: vi.fn() }],
  })),
}));
vi.mock("lightweight-charts", () => ({
  createChart: mocks.createChart,
  createSeriesMarkers: vi.fn(() => ({ setMarkers: vi.fn() })),
  CandlestickSeries: "Candlestick",
  HistogramSeries: "Histogram",
  LineSeries: "Line",
  ColorType: { Solid: "solid" },
}));

import { PriceChart } from "./PriceChart";

const BARS = [{ time: 1700000000, open: 1, high: 2, low: 0.5, close: 1.5, volume: 10 }];

describe("PriceChart re-render", () => {
  it("does not rebuild the chart when the parent re-renders with the same bars and no signals", () => {
    const { rerender } = render(<PriceChart bars={BARS} />);
    rerender(<PriceChart bars={BARS} />);
    rerender(<PriceChart bars={BARS} indicators={undefined} />);
    expect(mocks.createChart).toHaveBeenCalledTimes(1);
  });
});
