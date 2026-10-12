import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { DataRange } from "../../api/types";
import { Button, Field, Input, Select } from "../ui";
import { CheckField, Group } from "./Group";

export function DataGroup({ range, onChange, onLoad, loading, status, mainstreamOnly, setMainstreamOnly }: {
  range: DataRange; onChange: (r: DataRange) => void; onLoad: () => void; loading: boolean; status: string;
  mainstreamOnly: boolean; setMainstreamOnly: (v: boolean) => void;
}) {
  const symbols = useQuery({ queryKey: ["symbols", mainstreamOnly], queryFn: () => api.getSymbols(mainstreamOnly) });
  const intervals = useQuery({ queryKey: ["intervals"], queryFn: api.getIntervals });
  return (
    <Group title="数据获取">
      <Field label="交易对">
        <Select value={range.symbol} onChange={(e) => onChange({ ...range, symbol: e.target.value })}>
          {(symbols.data?.symbols ?? [range.symbol]).map((s) => <option key={s}>{s}</option>)}
        </Select>
      </Field>
      <CheckField label="仅显示主流货币" checked={mainstreamOnly} onChange={setMainstreamOnly} />
      <Field label="周期">
        <Select value={range.interval} onChange={(e) => onChange({ ...range, interval: e.target.value })}>
          {(intervals.data?.intervals ?? [range.interval]).map((i) => <option key={i}>{i}</option>)}
        </Select>
      </Field>
      <Field label="开始日期"><Input type="date" value={range.start} onChange={(e) => onChange({ ...range, start: e.target.value })} /></Field>
      <Field label="结束日期"><Input type="date" value={range.end} onChange={(e) => onChange({ ...range, end: e.target.value })} /></Field>
      <div className="flex items-center justify-between">
        <Button type="button" onClick={onLoad} disabled={loading}>{loading ? "加载中..." : "加载数据"}</Button>
        <span className="text-xs text-slate-500">{status}</span>
      </div>
    </Group>
  );
}
