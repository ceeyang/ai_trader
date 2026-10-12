import type { AnalysisPreset, DataRange } from "../../api/types";
import { Button } from "../ui";
import { BacktestGroup } from "./BacktestGroup";
import { DataGroup } from "./DataGroup";
import { IndicatorGroup } from "./IndicatorGroup";
import { PatternGroup } from "./PatternGroup";
import { SignalGroup } from "./SignalGroup";

export interface ParamPanelProps {
  range: DataRange; setRange: (r: DataRange) => void;
  mainstreamOnly: boolean; setMainstreamOnly: (v: boolean) => void;
  preset: AnalysisPreset; setPreset: (p: AnalysisPreset) => void;
  enabledPatterns: Set<string>; setEnabledPatterns: (s: Set<string>) => void;
  onLoad: () => void; loading: boolean; dataStatus: string;
  onAnalyze: () => void; analyzing: boolean;
  onBacktest: () => void; backtesting: boolean;
  onSavePreset: () => void; onLoadPreset: () => void; hasData: boolean;
}

export function ParamPanel(p: ParamPanelProps) {
  return (
    <aside className="flex w-80 shrink-0 flex-col gap-3">
      <DataGroup range={p.range} onChange={p.setRange} onLoad={p.onLoad} loading={p.loading} status={p.dataStatus}
        mainstreamOnly={p.mainstreamOnly} setMainstreamOnly={p.setMainstreamOnly} />
      <IndicatorGroup value={p.preset.indicators} onChange={(v) => p.setPreset({ ...p.preset, indicators: v })} />
      <PatternGroup enabled={p.enabledPatterns} onChange={p.setEnabledPatterns} />
      <SignalGroup value={p.preset.signals} onChange={(v) => p.setPreset({ ...p.preset, signals: v })} />
      <BacktestGroup value={p.preset.backtest} onChange={(v) => p.setPreset({ ...p.preset, backtest: v })} />
      <div className="flex flex-wrap gap-2">
        <Button type="button" onClick={p.onAnalyze} disabled={!p.hasData || p.analyzing}>{p.analyzing ? "分析中..." : "开始分析"}</Button>
        <Button type="button" onClick={p.onBacktest} disabled={!p.hasData || p.backtesting}>{p.backtesting ? "回测中..." : "运行回测"}</Button>
        <Button type="button" onClick={p.onSavePreset} className="bg-slate-600">保存配置</Button>
        <Button type="button" onClick={p.onLoadPreset} className="bg-slate-600">加载配置</Button>
      </div>
    </aside>
  );
}
