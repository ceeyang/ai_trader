import { useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { api } from "../../api/client";
import type { DCARequest } from "../../api/types";
import { Button, Field, Input, Select, isoDaysAgo } from "../ui";

export function DcaForm({ onSubmit, loading }: { onSubmit: (req: DCARequest) => void; loading: boolean }) {
  const [mainstreamOnly, setMainstreamOnly] = useState(true);
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [amount, setAmount] = useState(200);
  const [day, setDay] = useState(10);
  const [startDate, setStartDate] = useState(isoDaysAgo(365));
  const [endDate, setEndDate] = useState(isoDaysAgo(0));
  const symbols = useQuery({ queryKey: ["symbols", mainstreamOnly], queryFn: () => api.getSymbols(mainstreamOnly) });

  function submit(e: FormEvent) {
    e.preventDefault();
    onSubmit({ symbol, amount, day, start_date: startDate, end_date: endDate || null });
  }

  return (
    <form onSubmit={submit} className="grid grid-cols-2 gap-3 md:grid-cols-3">
      <Field label="交易对">
        <Select value={symbol} onChange={(e) => setSymbol(e.target.value)}>
          {(symbols.data?.symbols ?? [symbol]).map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </Select>
      </Field>
      <label className="flex items-end gap-2 text-sm">
        <input type="checkbox" checked={mainstreamOnly} onChange={(e) => setMainstreamOnly(e.target.checked)} />
        仅显示主流货币
      </label>
      <Field label="定投金额 (USDT)">
        <Input type="number" min={1} value={amount} onChange={(e) => setAmount(Number(e.target.value))} />
      </Field>
      <Field label="每月定投日">
        <Input type="number" min={1} max={31} value={day} onChange={(e) => setDay(Number(e.target.value))} />
      </Field>
      <Field label="开始日期">
        <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
      </Field>
      <Field label="结束日期">
        <Input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
      </Field>
      <div className="col-span-2 md:col-span-3">
        <Button type="submit" disabled={loading}>
          {loading ? "计算中..." : "计算收益"}
        </Button>
      </div>
    </form>
  );
}
