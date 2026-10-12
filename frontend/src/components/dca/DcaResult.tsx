import type { DCAResponse } from "../../api/types";
import { Card, fmt } from "../ui";

export function DcaResult({ data }: { data: DCAResponse }) {
  const stats: [string, string][] = [
    ["币种", data.symbol],
    ["投资次数", String(data.investment_count)],
    ["总投入", `${fmt.num(data.total_invested)} USDT`],
    ["当前价格", `${fmt.num(data.current_price)} USDT`],
    ["当前总价值", `${fmt.num(data.total_value)} USDT`],
    ["收益", `${fmt.num(data.profit)} USDT`],
    ["收益率", fmt.pct(data.profit_rate)],
    ["平均成本", `${fmt.num(data.average_cost)} USDT`],
    ["累计买入", `${fmt.num(data.total_coins, 6)}`],
  ];
  return (
    <div className="flex flex-col gap-4">
      <Card title="收益汇总">
        <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm md:grid-cols-3">
          {stats.map(([k, v]) => (
            <div key={k} className="flex justify-between border-b border-slate-100 py-1">
              <dt className="text-slate-500">{k}</dt>
              <dd className="font-medium">{v}</dd>
            </div>
          ))}
        </dl>
      </Card>
      <Card title="定投明细">
        <table className="w-full text-sm">
          <thead className="text-left text-slate-500">
            <tr>
              <th className="py-1">日期</th>
              <th>价格 (USDT)</th>
              <th>买入数量</th>
            </tr>
          </thead>
          <tbody>
            {data.records.map((r) => (
              <tr key={r.date} className="border-t border-slate-100">
                <td className="py-1">{r.date}</td>
                <td>{fmt.num(r.price)}</td>
                <td>{fmt.num(r.coins, 6)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
