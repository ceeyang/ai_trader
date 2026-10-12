import {
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  LineSeries,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type SeriesMarker,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef } from "react";
import type { AnalysisResponse, Bar } from "../../api/types";

const OVERLAY_PREFIXES = ["sma_", "ema_", "bb_"];
const PANES: { name: string; keys: string[] }[] = [
  { name: "RSI", keys: ["rsi"] },
  { name: "MACD", keys: ["macd_dif", "macd_dea", "macd_hist"] },
  { name: "KDJ", keys: ["kdj_k", "kdj_d", "kdj_j"] },
];
const COLORS = ["#2563eb", "#d97706", "#7c3aed", "#059669", "#dc2626", "#0891b2", "#9333ea"];

function lineData(bars: Bar[], values: (number | null)[]) {
  const out: { time: UTCTimestamp; value: number }[] = [];
  values.forEach((v, i) => {
    if (v != null && bars[i]) out.push({ time: bars[i].time as UTCTimestamp, value: v });
  });
  return out;
}

export interface PriceChartProps {
  bars: Bar[];
  indicators?: AnalysisResponse["indicators"];
  entry?: number[];
  exit?: number[];
}

export function PriceChart({ bars, indicators, entry = [], exit = [] }: PriceChartProps) {
  const container = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!container.current) return;
    const chart = createChart(container.current, {
      height: 620,
      layout: { background: { type: ColorType.Solid, color: "#ffffff" }, textColor: "#334155", panes: { separatorColor: "#e2e8f0" } },
      grid: { vertLines: { color: "#f1f5f9" }, horzLines: { color: "#f1f5f9" } },
      timeScale: { timeVisible: true, secondsVisible: false },
    });
    chartRef.current = chart;

    const candles = chart.addSeries(CandlestickSeries, {
      upColor: "#16a34a", downColor: "#dc2626", borderVisible: false, wickUpColor: "#16a34a", wickDownColor: "#dc2626",
    });
    candles.setData(bars.map((b) => ({ time: b.time as UTCTimestamp, open: b.open, high: b.high, low: b.low, close: b.close })));

    const volume = chart.addSeries(HistogramSeries, { priceScaleId: "volume", priceFormat: { type: "volume" } });
    volume.priceScale().applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
    volume.setData(bars.map((b) => ({ time: b.time as UTCTimestamp, value: b.volume, color: b.close >= b.open ? "#86efac" : "#fca5a5" })));

    let colorIdx = 0;
    const nextColor = () => COLORS[colorIdx++ % COLORS.length];
    if (indicators) {
      for (const key of Object.keys(indicators)) {
        if (OVERLAY_PREFIXES.some((p) => key.startsWith(p))) {
          chart.addSeries(LineSeries, { color: nextColor(), lineWidth: 1, title: key, priceLineVisible: false, lastValueVisible: false })
            .setData(lineData(bars, indicators[key]));
        }
      }
      PANES.forEach((pane, i) => {
        const present = pane.keys.filter((k) => indicators[k]);
        present.forEach((k) => {
          chart.addSeries(LineSeries, { color: nextColor(), lineWidth: 1, title: k, priceLineVisible: false, lastValueVisible: false }, i + 1)
            .setData(lineData(bars, indicators[k]));
        });
      });
    }

    const markers: SeriesMarker<UTCTimestamp>[] = [
      ...entry.map((t) => ({ time: t as UTCTimestamp, position: "belowBar" as const, color: "#16a34a", shape: "arrowUp" as const, text: "入" })),
      ...exit.map((t) => ({ time: t as UTCTimestamp, position: "aboveBar" as const, color: "#dc2626", shape: "arrowDown" as const, text: "出" })),
    ].sort((a, b) => a.time - b.time);
    createSeriesMarkers(candles, markers);
    chart.timeScale().fitContent();

    const onResize = () => container.current && chart.applyOptions({ width: container.current.clientWidth });
    onResize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chart.remove();
      chartRef.current = null;
    };
  }, [bars, indicators, entry, exit]);

  return <div ref={container} className="w-full" data-testid="price-chart" />;
}
