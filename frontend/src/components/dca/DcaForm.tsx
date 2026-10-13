import { useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { api } from "../../api/client";
import type { AllocationIn, DCAFrequency, DCARequest } from "../../api/types";
import { Button, Field, Input, Select, isoDaysAgo } from "../ui";

export function DcaForm({ onSubmit, loading }: { onSubmit: (req: DCARequest) => void; loading: boolean }) {
  const [mainstreamOnly, setMainstreamOnly] = useState(true);
  const [frequency, setFrequency] = useState<DCAFrequency>("monthly");
  const [day, setDay] = useState(10);
  const [hour, setHour] = useState<number | null>(null);
  const [amount, setAmount] = useState(200);
  const [startDate, setStartDate] = useState(isoDaysAgo(365));
  const [endDate, setEndDate] = useState(isoDaysAgo(0));
  const [allocations, setAllocations] = useState<AllocationIn[]>([{ symbol: "BTCUSDT", weight: 1 }]);
  const symbols = useQuery({ queryKey: ["symbols", mainstreamOnly], queryFn: () => api.getSymbols(mainstreamOnly) });
  const symbolOptions = symbols.data?.symbols ?? ["BTCUSDT"];
  const totalWeight = allocations.reduce((s, a) => s + (a.weight > 0 ? a.weight : 0), 0);

  const update = (i: number, patch: Partial<AllocationIn>) =>
    setAllocations(allocations.map((a, idx) => (idx === i ? { ...a, ...patch } : a)));
  const addRow = () => {
    const next = symbolOptions.find((s) => !allocations.some((a) => a.symbol === s)) ?? symbolOptions[0];
    setAllocations([...allocations, { symbol: next, weight: 1 }]);
  };
  const removeRow = (i: number) => setAllocations(allocations.filter((_, idx) => idx !== i));

  function submit(e: FormEvent) {
    e.preventDefault();
    onSubmit({ frequency, day, hour, amount, start_date: startDate, end_date: endDate || null, allocations });
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <fieldset className="flex flex-col gap-1 text-sm">
          <legend className="text-slate-600">定投频率</legend>
          <div className="flex gap-4 pt-1">
            <label className="flex items-center gap-1">
              <input type="radio" name="frequency" value="monthly" checked={frequency === "monthly"} onChange={() => setFrequency("monthly")} />
              每月
            </label>
            <label className="flex items-center gap-1">
              <input type="radio" name="frequency" value="daily" checked={frequency === "daily"} onChange={() => setFrequency("daily")} />
              每日
            </label>
          </div>
        </fieldset>
        {frequency === "monthly" && (
          <Field label="每月定投日">
            <Input type="number" min={1} max={31} value={day} onChange={(e) => setDay(Number(e.target.value))} />
          </Field>
        )}
        <Field label="定投时间 (北京时间)">
          <Select value={hour === null ? "" : String(hour)} onChange={(e) => setHour(e.target.value === "" ? null : Number(e.target.value))}>
            <option value="">日线收盘价（默认）</option>
            {Array.from({ length: 24 }, (_, h) => (
              <option key={h} value={h}>{String(h).padStart(2, "0")}:00</option>
            ))}
          </Select>
        </Field>
        <Field label={allocations.length > 1 ? "每期总额 (USDT)" : "定投金额 (USDT)"}>
          <Input type="number" min={1} value={amount} onChange={(e) => setAmount(Number(e.target.value))} />
        </Field>
        <Field label="开始日期">
          <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
        </Field>
        <Field label="结束日期">
          <Input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
        </Field>
      </div>

      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-4 text-sm">
          <span className="text-slate-600">{allocations.length > 1 ? "组合币种与权重" : "币种"}</span>
          <label className="flex items-center gap-1">
            <input type="checkbox" checked={mainstreamOnly} onChange={(e) => setMainstreamOnly(e.target.checked)} />
            仅显示主流货币
          </label>
        </div>
        {allocations.map((a, i) => (
          <div key={i} data-testid="allocation-row" className="flex items-center gap-2 text-sm">
            <Select aria-label="币种" value={a.symbol} onChange={(e) => update(i, { symbol: e.target.value })} className="w-40">
              {(symbolOptions.includes(a.symbol) ? symbolOptions : [a.symbol, ...symbolOptions]).map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </Select>
            {allocations.length > 1 && (
              <>
                <Input aria-label="权重" type="number" min={0} step={1} value={a.weight} onChange={(e) => update(i, { weight: Number(e.target.value) })} className="w-24" />
                <span className="w-16 text-slate-500">{totalWeight > 0 && a.weight > 0 ? `${((a.weight / totalWeight) * 100).toFixed(1)}%` : "-"}</span>
                <button type="button" onClick={() => removeRow(i)} className="text-slate-400 hover:text-red-600" aria-label="删除币种">✕</button>
              </>
            )}
          </div>
        ))}
        <div>
          <button type="button" onClick={addRow} className="text-sm text-blue-700 hover:underline">添加币种</button>
          {allocations.length > 1 && <span className="ml-3 text-xs text-slate-500">权重按比例归一化，每期总额按比例分配到各币种</span>}
        </div>
      </div>

      <div>
        <Button type="submit" disabled={loading || allocations.length === 0}>
          {loading ? "计算中..." : "计算收益"}
        </Button>
      </div>
    </form>
  );
}
