import { useState } from "react";
import type { AnalysisResponse, BacktestResponse, Bar } from "../../api/types";
import { fmt } from "../ui";

const TABS = ["分析结果", "信号详情", "回测结果"] as const;
type Tab = (typeof TABS)[number];

function closeAt(bars: Bar[], t: number) {
  return bars.find((b) => b.time === t)?.close;
}

export function ResultTabs({ analysis, backtest, bars }: { analysis?: AnalysisResponse; backtest?: BacktestResponse; bars: Bar[] }) {
  const [tab, setTab] = useState<Tab>("分析结果");
  return (
    <div className="rounded-lg border border-slate-200 bg-white">
      <div role="tablist" className="flex border-b border-slate-200">
        {TABS.map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm ${tab === t ? "border-b-2 border-slate-900 font-semibold" : "text-slate-500"}`}>
            {t}
          </button>
        ))}
      </div>
      <div role="tabpanel" className="p-4 text-sm">
        {tab === "分析结果" && (analysis ? <AnalysisSummary a={analysis} /> : <Empty text="请先加载数据并开始分析" />)}
        {tab === "信号详情" && (analysis ? <SignalDetail a={analysis} bars={bars} /> : <Empty text="请先开始分析" />)}
        {tab === "回测结果" && (backtest ? <BacktestSummary b={backtest} /> : <Empty text="请先运行回测" />)}
      </div>
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return <p className="text-slate-400">{text}</p>;
}

function AnalysisSummary({ a }: { a: AnalysisResponse }) {
  return (
    <div className="flex flex-col gap-3">
      <p>入场信号 <b>{a.entry_signals.length}</b> 个，出场信号 <b>{a.exit_signals.length}</b> 个</p>
      <table className="w-full">
        <thead className="text-left text-slate-500"><tr><th className="py-1">信号</th><th>频率</th><th>平均1日收益</th><th>正收益比例</th></tr></thead>
        <tbody>
          {Object.entries(a.effectiveness).map(([name, s]) => (
            <tr key={name} className="border-t border-slate-100">
              <td className="py-1 font-mono">{name}</td><td>{fmt.ratio(s.frequency)}</td><td>{fmt.ratio(s.avg_price_change_1d)}</td><td>{fmt.ratio(s.positive_rate)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SignalDetail({ a, bars }: { a: AnalysisResponse; bars: Bar[] }) {
  const rows = (times: number[], kind: string) =>
    times.slice(-20).map((t) => (
      <tr key={`${kind}-${t}`} className="border-t border-slate-100"><td className="py-1">{kind}</td><td>{fmt.date(t)}</td><td>{fmt.num(closeAt(bars, t))}</td></tr>
    ));
  return (
    <table className="w-full">
      <thead className="text-left text-slate-500"><tr><th className="py-1">类型</th><th>时间</th><th>价格</th></tr></thead>
      <tbody>
        {rows(a.entry_signals, "入场")}
        {rows(a.exit_signals, "出场")}
        {a.entry_signals.length + a.exit_signals.length === 0 && <tr><td colSpan={3} className="py-2 text-slate-400">未发现信号</td></tr>}
      </tbody>
    </table>
  );
}

function BacktestSummary({ b }: { b: BacktestResponse }) {
  const stats: [string, string][] = [
    ["总交易次数", String(b.total_trades)], ["盈利交易", String(b.winning_trades)], ["亏损交易", String(b.losing_trades)],
    ["胜率", fmt.ratio(b.win_rate)], ["总收益率", fmt.ratio(b.total_return)], ["总盈亏", fmt.num(b.total_pnl)],
    ["最大回撤", fmt.num(b.max_drawdown)], ["夏普比率", fmt.num(b.sharpe_ratio)], ["平均持仓天数", fmt.num(b.avg_trade_duration, 1)],
  ];
  return (
    <div className="flex flex-col gap-3">
      <dl className="grid grid-cols-3 gap-2">
        {stats.map(([k, v]) => (
          <div key={k} className="rounded bg-slate-50 p-2"><dt className="text-xs text-slate-500">{k}</dt><dd className="font-semibold">{v}</dd></div>
        ))}
      </dl>
      <table className="w-full">
        <thead className="text-left text-slate-500"><tr><th className="py-1">入场</th><th>出场</th><th>入场价</th><th>出场价</th><th>盈亏</th><th>持仓(天)</th></tr></thead>
        <tbody>
          {b.trades.slice(0, 50).map((t, i) => (
            <tr key={i} className="border-t border-slate-100">
              <td className="py-1">{fmt.date(t.entry_time)}</td><td>{fmt.date(t.exit_time)}</td><td>{fmt.num(t.entry_price)}</td><td>{fmt.num(t.exit_price)}</td>
              <td className={t.pnl >= 0 ? "text-green-700" : "text-red-700"}>{fmt.num(t.pnl)} ({fmt.ratio(t.pnl_percent)})</td><td>{t.duration}</td>
            </tr>
          ))}
          {b.trades.length === 0 && <tr><td colSpan={6} className="py-2 text-slate-400">无交易记录</td></tr>}
        </tbody>
      </table>
    </div>
  );
}
