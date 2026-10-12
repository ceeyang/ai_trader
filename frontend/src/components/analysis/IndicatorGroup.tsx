import type { IndicatorParams } from "../../api/types";
import { Group, NumberField } from "./Group";

export function IndicatorGroup({ value, onChange }: { value: IndicatorParams; onChange: (v: IndicatorParams) => void }) {
  const set = (patch: Partial<IndicatorParams>) => onChange({ ...value, ...patch });
  return (
    <Group title="技术指标" defaultOpen={false}>
      <label className="flex items-center justify-between gap-2 text-sm">
        <span className="text-slate-600">均线周期 (逗号分隔)</span>
        <input value={value.sma_periods.join(",")} className="w-32 rounded border border-slate-300 px-2 py-0.5 text-right"
          onChange={(e) => set({ sma_periods: e.target.value.split(",").map((s) => Number(s.trim())).filter((n) => n > 0) })} />
      </label>
      <NumberField label="MACD 快线" value={value.macd_fast} onChange={(v) => set({ macd_fast: v })} />
      <NumberField label="MACD 慢线" value={value.macd_slow} onChange={(v) => set({ macd_slow: v })} />
      <NumberField label="MACD 信号" value={value.macd_signal} onChange={(v) => set({ macd_signal: v })} />
      <NumberField label="RSI 周期" value={value.rsi_period} onChange={(v) => set({ rsi_period: v })} />
      <NumberField label="KDJ K" value={value.kdj_k} onChange={(v) => set({ kdj_k: v })} />
      <NumberField label="KDJ D" value={value.kdj_d} onChange={(v) => set({ kdj_d: v })} />
      <NumberField label="KDJ J" value={value.kdj_j} onChange={(v) => set({ kdj_j: v })} />
      <NumberField label="布林周期" value={value.bb_period} onChange={(v) => set({ bb_period: v })} />
      <NumberField label="布林标准差" value={value.bb_std} step={0.1} onChange={(v) => set({ bb_std: v })} />
    </Group>
  );
}
