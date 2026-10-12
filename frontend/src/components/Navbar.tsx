import { NavLink } from "react-router-dom";

const ENABLED = [
  { to: "/dca", label: "定投计算" },
  { to: "/analysis", label: "技术分析" },
];
const DISABLED = ["策略管理", "回测", "监控", "设置"];

export function Navbar() {
  return (
    <header className="bg-slate-900 text-slate-100">
      <nav className="mx-auto flex max-w-7xl items-center gap-1 px-4 py-2" aria-label="主导航">
        <span className="mr-6 text-lg font-semibold">AI Trader</span>
        {ENABLED.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              `rounded px-3 py-1.5 text-sm ${isActive ? "bg-slate-700" : "hover:bg-slate-800"}`
            }
          >
            {item.label}
          </NavLink>
        ))}
        {DISABLED.map((label) => (
          <span key={label} aria-disabled="true" className="cursor-not-allowed px-3 py-1.5 text-sm text-slate-500">
            {label}
          </span>
        ))}
      </nav>
    </header>
  );
}
