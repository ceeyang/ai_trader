import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { DEFAULT_PRESET, type AnalysisPreset, type DataRange } from "../api/types";
import { ParamPanel } from "../components/analysis/ParamPanel";
import { PATTERN_LABELS } from "../components/analysis/PatternGroup";
import { PriceChart } from "../components/analysis/PriceChart";
import { ResultTabs } from "../components/analysis/ResultTabs";
import { ErrorBanner, errorMessage, isoDaysAgo } from "../components/ui";

export function AnalysisPage() {
  const [range, setRange] = useState<DataRange>({ symbol: "BTCUSDT", interval: "1d", start: isoDaysAgo(365), end: isoDaysAgo(0) });
  const [mainstreamOnly, setMainstreamOnly] = useState(true);
  const [preset, setPreset] = useState<AnalysisPreset>(DEFAULT_PRESET);
  const [enabledPatterns, setEnabledPatterns] = useState(new Set(Object.keys(PATTERN_LABELS)));
  const [loadedRange, setLoadedRange] = useState<DataRange | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const serverPreset = useQuery({ queryKey: ["preset"], queryFn: api.getPreset });
  useEffect(() => { if (serverPreset.data) setPreset(serverPreset.data); }, [serverPreset.data]);

  const klines = useQuery({ queryKey: ["klines", loadedRange], queryFn: () => api.getKlines(loadedRange!), enabled: !!loadedRange });
  const analysis = useMutation({ mutationFn: api.runAnalysis });
  const backtest = useMutation({ mutationFn: api.runBacktest });
  const savePreset = useMutation({ mutationFn: api.savePreset, onSuccess: () => setNotice("配置已保存") });

  const bars = klines.data?.bars ?? [];
  const error = [klines.error, analysis.error, backtest.error, savePreset.error].find(Boolean);
  const dataStatus = klines.isFetching ? "加载中..." : bars.length ? `已加载 ${bars.length} 根K线` : "未加载";

  const filteredIndicators = useMemo(() => analysis.data?.indicators, [analysis.data]);
  const request = () => ({ data: loadedRange ?? range, indicators: preset.indicators, signals: preset.signals });

  return (
    <div className="flex flex-col gap-3">
      <h1 className="text-xl font-semibold">技术分析</h1>
      <ErrorBanner message={error ? errorMessage(error) : null} />
      {notice && <p className="text-sm text-green-700">{notice}</p>}
      <div className="flex gap-4">
        <ParamPanel
          range={range} setRange={setRange} mainstreamOnly={mainstreamOnly} setMainstreamOnly={setMainstreamOnly}
          preset={preset} setPreset={setPreset} enabledPatterns={enabledPatterns} setEnabledPatterns={setEnabledPatterns}
          onLoad={() => { setNotice(null); setLoadedRange({ ...range }); }} loading={klines.isFetching} dataStatus={dataStatus}
          onAnalyze={() => analysis.mutate(request())} analyzing={analysis.isPending}
          onBacktest={() => backtest.mutate({ ...request(), backtest: preset.backtest })} backtesting={backtest.isPending}
          onSavePreset={() => savePreset.mutate(preset)}
          onLoadPreset={() => serverPreset.refetch().then((r) => r.data && setPreset(r.data))}
          hasData={bars.length > 0}
        />
        <div className="flex min-w-0 flex-1 flex-col gap-3">
          <div className="rounded-lg border border-slate-200 bg-white p-2">
            {bars.length ? (
              <PriceChart bars={bars} indicators={filteredIndicators} entry={analysis.data?.entry_signals} exit={analysis.data?.exit_signals} />
            ) : (
              <p className="p-8 text-center text-slate-400">加载数据后显示K线图</p>
            )}
          </div>
          {analysis.data && (
            <p className="text-xs text-slate-500">
              形态命中：{Object.entries(analysis.data.patterns).filter(([k]) => enabledPatterns.has(k)).map(([k, v]) => `${PATTERN_LABELS[k] ?? k} ${v.length}`).join(" · ")}
            </p>
          )}
          <ResultTabs analysis={analysis.data} backtest={backtest.data} bars={bars} />
        </div>
      </div>
    </div>
  );
}
