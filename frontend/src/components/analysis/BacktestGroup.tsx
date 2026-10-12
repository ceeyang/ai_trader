import type { BacktestParams } from "../../api/types";
import { Group, NumberField } from "./Group";

export function BacktestGroup({ value, onChange }: { value: BacktestParams; onChange: (v: BacktestParams) => void }) {
  const set = (patch: Partial<BacktestParams>) => onChange({ ...value, ...patch });
  return (
    <Group title="回测参数" defaultOpen={false}>
      <NumberField label="初始资金" value={value.initial_capital} step={1000} onChange={(v) => set({ initial_capital: v })} />
      <NumberField label="仓位比例" value={value.position_size} step={0.05} onChange={(v) => set({ position_size: v })} />
      <NumberField label="手续费率" value={value.commission_rate} step={0.0005} onChange={(v) => set({ commission_rate: v })} />
      <NumberField label="滑点率" value={value.slippage_rate} step={0.0001} onChange={(v) => set({ slippage_rate: v })} />
    </Group>
  );
}
