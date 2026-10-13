import type { DCAResponse } from "../../api/types";
import { Card, fmt } from "../ui";

const FREQ_LABEL = { daily: "每日", monthly: "每月" } as const;

function Stat({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between border-b border-slate-100 py-1">
      <dt className="text-slate-500">{k}</dt>
      <dd className="font-medium">{v}</dd>
    </div>
  );
}

export function DcaResult({ data }: { data: DCAResponse }) {
  const portfolio = data.legs.length > 1;
  const summary: [string, string][] = [
    ["频率", FREQ_LABEL[data.frequency]],
    ["定投时间", data.invest_hour == null ? "日线收盘价" : `${String(data.invest_hour).padStart(2, "0")}:00 (北京时间)`],
    ["投资期数", String(data.investment_count)],
    ["总投入", `${fmt.num(data.total_invested)} USDT`],
    ["当前总价值", `${fmt.num(data.total_value)} USDT`],
    ["收益", `${fmt.num(data.profit)} USDT`],
    ["收益率", fmt.pct(data.profit_rate)],
  ];
  if (!portfolio) {
    const leg = data.legs[0];
    summary.unshift(["币种", leg.symbol]);
    summary.push(["当前价格", `${fmt.num(leg.current_price)} USDT`], ["平均成本", `${fmt.num(leg.average_cost)} USDT`], ["累计买入", fmt.num(leg.total_coins, 6)]);
  }
  return (
    <div className="flex flex-col gap-4">
      <Card title={portfolio ? "组合收益汇总" : "收益汇总"}>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm md:grid-cols-3">
          {summary.map(([k, v]) => <Stat key={k} k={k} v={v} />)}
        </dl>
      </Card>
      {portfolio && (
        <Card title="各币种">
          <table className="w-full text-sm">
            <thead className="text-left text-slate-500">
              <tr><th className="py-1">币种</th><th>权重</th><th>投入</th><th>当前价值</th><th>收益</th><th>收益率</th><th>均价</th><th>累计买入</th></tr>
            </thead>
            <tbody>
              {data.legs.map((l) => (
                <tr key={l.symbol} className="border-t border-slate-100">
                  <td className="py-1 font-medium">{l.symbol}</td><td>{fmt.pct(l.weight * 100, 1)}</td><td>{fmt.num(l.total_invested)}</td>
                  <td>{fmt.num(l.total_value)}</td><td className={l.profit >= 0 ? "text-green-700" : "text-red-700"}>{fmt.num(l.profit)}</td>
                  <td>{fmt.pct(l.profit_rate)}</td><td>{fmt.num(l.average_cost)}</td><td>{fmt.num(l.total_coins, 6)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
      <Card title="定投明细">
        <table className="w-full text-sm">
          <thead className="text-left text-slate-500">
            <tr>
              <th className="py-1">日期</th>
              {data.legs.map((l) => <th key={l.symbol}>{l.symbol} 价格 / 买入</th>)}
              {portfolio && <th>当期合计</th>}
            </tr>
          </thead>
          <tbody>
            {data.records.map((p, i) => (
              <tr key={p.date} className="border-t border-slate-100">
                <td className="py-1">{p.date}</td>
                {data.legs.map((l) => {
                  const r = l.records[i]?.date === p.date ? l.records[i] : l.records.find((x) => x.date === p.date);
                  return <td key={l.symbol}>{r ? `${fmt.num(r.price)} / ${fmt.num(r.coins, 6)}` : "-"}</td>;
                })}
                {portfolio && <td>{fmt.num(p.amount)}</td>}
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
