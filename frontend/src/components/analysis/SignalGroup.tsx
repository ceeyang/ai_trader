import type { SignalParams } from "../../api/types";
import { Select } from "../ui";
import { CheckField, Group, NumberField } from "./Group";

const FLAGS: [keyof SignalParams, string][] = [
  ["trend_required", "趋势"], ["macd_required", "MACD"], ["rsi_required", "RSI"], ["kdj_required", "KDJ"],
  ["bb_required", "布林带"], ["pattern_required", "K线形态"], ["volume_required", "成交量确认 (仅入场)"],
];

export function SignalGroup({ value, onChange }: { value: SignalParams; onChange: (v: SignalParams) => void }) {
  const set = (patch: Partial<SignalParams>) => onChange({ ...value, ...patch });
  return (
    <Group title="信号条件">
      <NumberField label="RSI 超卖" value={value.rsi_oversold} onChange={(v) => set({ rsi_oversold: v })} />
      <NumberField label="RSI 超买" value={value.rsi_overbought} onChange={(v) => set({ rsi_overbought: v })} />
      {FLAGS.map(([k, label]) => (
        <CheckField key={k} label={label} checked={value[k] as boolean} onChange={(v) => set({ [k]: v } as Partial<SignalParams>)} />
      ))}
      <label className="flex items-center justify-between gap-2 text-sm">
        <span className="text-slate-600">入场组合方式</span>
        <Select value={value.combination} onChange={(e) => set({ combination: e.target.value as "all" | "min" })}>
          <option value="all">满足全部条件</option>
          <option value="min">满足最少条件数</option>
        </Select>
      </label>
      <NumberField label="最少条件数" value={value.min_conditions} min={1} onChange={(v) => set({ min_conditions: v })} />
    </Group>
  );
}
