import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => {
  const setData = vi.fn<(data: unknown[]) => void>();
  const addSeries = vi.fn((_def: unknown, _opts?: unknown, _pane?: number) => ({
    setData,
    priceScale: () => ({ applyOptions: vi.fn() }),
  }));
  const createSeriesMarkers = vi.fn(() => ({ setMarkers: vi.fn() }));
  return { setData, addSeries, createSeriesMarkers };
});

vi.mock("lightweight-charts", () => ({
  createChart: vi.fn(() => ({
    addSeries: mocks.addSeries,
    timeScale: () => ({ subscribeVisibleLogicalRangeChange: vi.fn(), setVisibleLogicalRange: vi.fn(), fitContent: vi.fn() }),
    remove: vi.fn(),
    removeSeries: vi.fn(),
    panes: () => [{ setStretchFactor: vi.fn() }, { setStretchFactor: vi.fn() }],
    applyOptions: vi.fn(),
    priceScale: () => ({ applyOptions: vi.fn() }),
  })),
  createSeriesMarkers: mocks.createSeriesMarkers,
  CandlestickSeries: "Candlestick",
  HistogramSeries: "Histogram",
  LineSeries: "Line",
  ColorType: { Solid: "solid" },
}));

import { PriceChart } from "./PriceChart";

const BARS = [
  { time: 1700000000, open: 1, high: 2, low: 0.5, close: 1.5, volume: 10 },
  { time: 1700086400, open: 1.5, high: 2.5, low: 1, close: 2, volume: 12 },
];

describe("PriceChart", () => {
  it("adds one line series per indicator key, puts rsi on pane 1, and skips nulls", () => {
    render(
      <PriceChart bars={BARS} indicators={{ sma_5: [null, 1.2], bb_upper: [2, 2.1], rsi: [null, 55] }} entry={[1700086400]} exit={[]} />,
    );
    const lineCalls = mocks.addSeries.mock.calls.filter((c) => c[0] === "Line");
    expect(lineCalls.length).toBe(3);
    expect(lineCalls.map((c) => c[2])).toEqual([undefined, undefined, 1]);
    const fed = mocks.setData.mock.calls.flatMap((c) => c[0] as { value?: number | null }[]);
    expect(fed.some((p) => p.value === null)).toBe(false);
    expect(mocks.createSeriesMarkers).toHaveBeenCalledTimes(1);
    const markers = mocks.createSeriesMarkers.mock.calls[0] as unknown[];
    expect(markers[1]).toEqual([expect.objectContaining({ time: 1700086400, position: "belowBar" })]);
  });
});
