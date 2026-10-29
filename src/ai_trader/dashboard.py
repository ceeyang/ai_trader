"""Read-only local web dashboard (``ai-trader dashboard``).

Standard library only. Every request opens its own read-only SQLite connection
(``mode=ro``), so the dashboard can never write to the database the running
daemon owns. Each payload section is computed independently: a failing query
yields ``{"error": "<ExceptionType>"}`` for that section and nothing else.
"""

import json
import logging
import math
import os
import sqlite3
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

TABLES = (
    "news",
    "sentiments",
    "signals",
    "forward_returns",
    "mark_samples",
    "decisions",
    "risk_verdicts",
    "orders",
    "fills",
    "kv",
    "tuning_log",
)

MARK_WINDOW = timedelta(hours=2)
MAX_MARK_POINTS = 240
LOG_TAIL_LINES = 8


def _f(value: Any) -> float | None:
    """A DB TEXT/REAL decimal as a float (None stays None)."""
    if value is None:
        return None
    return float(Decimal(str(value)))


def _parse_ts(raw: str) -> datetime:
    ts = datetime.fromisoformat(raw)
    return ts if ts.tzinfo is not None else ts.replace(tzinfo=UTC)


def _age_s(raw: str | None, now: datetime) -> float | None:
    if not raw:
        return None
    return round((now - _parse_ts(raw)).total_seconds(), 1)


def _downsample(points: list[list[Any]], limit: int = MAX_MARK_POINTS) -> list[list[Any]]:
    """Keep at most `limit` points, evenly strided, always including the latest one."""
    if len(points) <= limit:
        return points
    step = math.ceil(len(points) / limit)
    out = points[::step]
    if out[-1] is not points[-1]:
        out = out[: limit - 1] + [points[-1]]
    return out[:limit]


def _connect(db_path: Path) -> sqlite3.Connection:
    uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=2.0)
    conn.row_factory = sqlite3.Row
    return conn


def _kv(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


# ---- process ---------------------------------------------------------------


def _pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        r = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return str(pid) in r.stdout.split()
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _tail(path: Path, lines: int = LOG_TAIL_LINES) -> list[str]:
    with path.open("rb") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        fh.seek(max(0, size - 8192))
        data = fh.read().decode("utf-8", errors="replace")
    return [ln for ln in data.splitlines() if ln.strip()][-lines:]


def _process(repo: Path) -> dict[str, Any]:
    data = repo / "data"
    pid_file = data / "paper-run.pid"
    pid: int | None = None
    if pid_file.exists():
        text = pid_file.read_text(encoding="utf-8-sig").strip()
        pid = int(text) if text.isdigit() else None
    alive = _pid_alive(pid) if pid is not None else False
    latest_file = data / "paper-run.latest"
    log_path: Path | None = None
    if latest_file.exists():
        stamp = latest_file.read_text(encoding="utf-8-sig").strip()
        if stamp:
            log_path = data / f"paper-run-{stamp}.log"
    err_path = log_path.with_name(log_path.stem + ".err.log") if log_path is not None else None
    # Python logging writes to stderr, so the daemon's lines usually land in the .err.log:
    # tail whichever of the two was written most recently.
    candidates = [p for p in (log_path, err_path) if p is not None and p.exists() and p.stat().st_size > 0]
    newest = max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None
    return {
        "pid": pid,
        "alive": alive,
        "log": str(log_path) if log_path is not None else None,
        "err_log": str(err_path) if err_path is not None else None,
        "log_tail_source": str(newest) if newest is not None else None,
        "log_tail": _tail(newest) if newest is not None else [],
    }


# ---- database sections -----------------------------------------------------


def _freshness(conn: sqlite3.Connection, symbols: list[str], now: datetime) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for symbol in symbols:
        row = conn.execute(
            "SELECT ts, price FROM mark_samples WHERE symbol = ? ORDER BY ts DESC LIMIT 1", (symbol,)
        ).fetchone()
        if row is None:
            out[symbol] = {"price": None, "ts": None, "age_s": None}
        else:
            out[symbol] = {"price": _f(row["price"]), "ts": row["ts"], "age_s": _age_s(row["ts"], now)}
    return out


def _counts(conn: sqlite3.Connection) -> dict[str, int | None]:
    counts: dict[str, int | None] = {}
    for table in TABLES:
        try:
            counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        except sqlite3.Error:
            counts[table] = None
    return counts


def _account(conn: sqlite3.Connection, marks: dict[str, Any] | None) -> dict[str, Any] | None:
    raw = _kv(conn, "paper_state")
    if raw is None:
        return None
    snap = json.loads(raw)
    positions = []
    for symbol, p in sorted(snap["positions"].items()):
        qty = Decimal(p["qty"])
        entry = Decimal(p["entry_price"])
        mark = None
        if isinstance(marks, dict) and isinstance(marks.get(symbol), dict):
            mark = marks[symbol].get("price")
        upnl = float((Decimal(str(mark)) - entry) * qty) if mark is not None else None
        positions.append(
            {
                "symbol": symbol,
                "side": "LONG" if qty > 0 else "SHORT",
                "qty": float(abs(qty)),
                "entry_price": float(entry),
                "mark_price": mark,
                "unrealized_pnl": upnl,
            }
        )
    resting = []
    for item in snap["pending"]:
        req = item["request"]
        resting.append(
            {
                "order_id": item.get("order_id"),
                "symbol": req.get("symbol"),
                "side": req.get("side"),
                "type": req.get("type"),
                "stop_price": _f(req.get("stop_price")),
                "quantity": _f(req.get("quantity")),
                "close_position": bool(req.get("close_position")),
                "client_order_id": req.get("client_order_id"),
            }
        )
    return {
        "wallet": _f(snap["wallet_balance"]),
        "realized_pnl": _f(snap["realized_pnl"]),
        "positions": positions,
        "resting_orders": resting,
    }


def _pnl(conn: sqlite3.Connection, now: datetime) -> dict[str, float]:
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    today = sum(
        (Decimal(r[0]) for r in conn.execute("SELECT realized_pnl FROM fills WHERE event_time >= ?", (midnight,))),
        Decimal(0),
    )
    total = sum((Decimal(r[0]) for r in conn.execute("SELECT realized_pnl FROM fills")), Decimal(0))
    return {"today_gross": float(today), "total_gross": float(total)}


def _marks(conn: sqlite3.Connection, symbols: list[str], now: datetime) -> dict[str, list[list[Any]]]:
    since = (now - MARK_WINDOW).isoformat()
    out: dict[str, list[list[Any]]] = {}
    for symbol in symbols:
        rows = conn.execute(
            "SELECT ts, price FROM mark_samples WHERE symbol = ? AND ts >= ? ORDER BY ts", (symbol, since)
        ).fetchall()
        out[symbol] = _downsample([[r["ts"], _f(r["price"])] for r in rows])
    return out


def _signals(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT created_at, detector, symbol, direction, strength, rationale FROM signals "
        "ORDER BY created_at DESC LIMIT 30"
    ).fetchall()
    return [
        {
            "ts": r["created_at"],
            "detector": r["detector"],
            "symbol": r["symbol"],
            "direction": r["direction"],
            "strength": r["strength"],
            "rationale": (r["rationale"] or "")[:80],
        }
        for r in rows
    ]


def _decisions(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT d.created_at, d.symbol, d.side, d.intent, d.notional_usdt, d.score, "
        "rv.approved, rv.reason, rv.adjusted_notional "
        "FROM decisions d LEFT JOIN risk_verdicts rv ON rv.decision_id = d.id "
        "ORDER BY d.created_at DESC LIMIT 20"
    ).fetchall()
    return [
        {
            "ts": r["created_at"],
            "symbol": r["symbol"],
            "side": r["side"],
            "intent": r["intent"],
            "notional_usdt": _f(r["notional_usdt"]),
            "score": r["score"],
            "approved": None if r["approved"] is None else bool(r["approved"]),
            "reason": r["reason"],
            "adjusted": _f(r["adjusted_notional"]),
        }
        for r in rows
    ]


def _orders(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT created_at, updated_at, symbol, side, type, role, qty, price, stop_price, status, "
        "avg_price, executed_qty, client_order_id FROM orders ORDER BY updated_at DESC LIMIT 20"
    ).fetchall()
    return [
        {
            "ts": r["updated_at"],
            "created_at": r["created_at"],
            "symbol": r["symbol"],
            "side": r["side"],
            "type": r["type"],
            "role": r["role"],
            "qty": _f(r["qty"]),
            "price": _f(r["price"]),
            "stop_price": _f(r["stop_price"]),
            "status": r["status"],
            "avg_price": _f(r["avg_price"]),
            "executed_qty": _f(r["executed_qty"]),
            "client_order_id": r["client_order_id"],
        }
        for r in rows
    ]


def _fills(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT event_time, symbol, side, price, qty, realized_pnl, commission, client_order_id "
        "FROM fills ORDER BY event_time DESC LIMIT 20"
    ).fetchall()
    return [
        {
            "ts": r["event_time"],
            "symbol": r["symbol"],
            "side": r["side"],
            "price": _f(r["price"]),
            "qty": _f(r["qty"]),
            "realized_pnl": _f(r["realized_pnl"]),
            "commission": _f(r["commission"]),
            "client_order_id": r["client_order_id"],
        }
        for r in rows
    ]


def _effectiveness(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT s.detector AS detector, fr.horizon_s AS horizon_s, COUNT(*) AS n, "
        "AVG(fr.ret) AS mean_ret, AVG(fr.ret > 0) AS hit_rate "
        "FROM forward_returns fr JOIN signals s ON s.id = fr.signal_id "
        "WHERE fr.ret IS NOT NULL GROUP BY s.detector, fr.horizon_s ORDER BY s.detector, fr.horizon_s"
    ).fetchall()
    return [
        {
            "detector": r["detector"],
            "horizon_s": r["horizon_s"],
            "n": r["n"],
            "mean_ret": r["mean_ret"],
            "hit_rate": r["hit_rate"],
        }
        for r in rows
    ]


def _tuning_log(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT ts, rule, field, old, new, reason FROM tuning_log ORDER BY id DESC LIMIT 20"
    ).fetchall()
    return [dict(r) for r in rows]


def _news_per_hour(conn: sqlite3.Connection, now: datetime) -> list[dict[str, Any]]:
    top = now.replace(minute=0, second=0, microsecond=0)
    start = top - timedelta(hours=23)
    rows = conn.execute(
        "SELECT substr(fetched_at, 1, 13) AS hour, COUNT(*) AS n FROM news "
        "WHERE fetched_at >= ? GROUP BY hour",
        (start.isoformat(),),
    ).fetchall()
    by_hour = {r["hour"]: r["n"] for r in rows}
    buckets = []
    for i in range(24):
        h = start + timedelta(hours=i)
        key = h.strftime("%Y-%m-%dT%H")
        buckets.append({"hour": h.isoformat(), "n": by_hour.get(key, 0)})
    return buckets


def _section(fn: Callable[[], Any]) -> Any:
    try:
        return fn()
    except Exception as exc:  # one bad section must not break the payload
        log.debug("dashboard section failed", exc_info=True)
        return {"error": type(exc).__name__}


def build_state(db_path: Path, repo: Path, symbols: list[str]) -> dict[str, Any]:
    """The whole dashboard payload, JSON-serialisable. Read-only."""
    now = datetime.now(UTC)
    state: dict[str, Any] = {
        "now_utc": now.isoformat(timespec="seconds"),
        "symbols": list(symbols),
        "db_path": str(db_path),
    }
    state["process"] = _section(lambda: _process(repo))

    conn: sqlite3.Connection | None = None
    connect_error: Exception | None = None
    try:
        if not Path(db_path).exists():
            raise FileNotFoundError(str(db_path))
        conn = _connect(Path(db_path))
    except (OSError, sqlite3.Error) as exc:
        connect_error = exc

    def db(fn: Callable[[sqlite3.Connection], Any]) -> Any:
        def run() -> Any:
            if conn is None:
                assert connect_error is not None
                raise connect_error
            return fn(conn)

        return _section(run)

    try:
        state["freshness"] = db(lambda c: _freshness(c, symbols, now))
        state["counts"] = db(_counts)
        marks = state["freshness"] if "error" not in state["freshness"] else None
        state["account"] = db(lambda c: _account(c, marks))
        state["kill_switch"] = db(lambda c: _kv(c, "kill_switch") == "1")
        state["stop_requested"] = db(lambda c: _kv(c, "stop_requested") == "1")
        state["effective_params"] = db(
            lambda c: json.loads(raw) if (raw := _kv(c, "tuning_effective")) is not None else None
        )
        state["pnl"] = db(lambda c: _pnl(c, now))
        state["marks"] = db(lambda c: _marks(c, symbols, now))
        state["signals"] = db(_signals)
        state["decisions"] = db(_decisions)
        state["orders"] = db(_orders)
        state["fills"] = db(_fills)
        state["effectiveness"] = db(_effectiveness)
        state["tuning_log"] = db(_tuning_log)
        state["news_per_hour"] = db(lambda c: _news_per_hour(c, now))
    finally:
        if conn is not None:
            conn.close()
    return state


# ---- HTTP ------------------------------------------------------------------


def _make_handler(db_path: Path, repo: Path, symbols: list[str]) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "ai-trader-dashboard"

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path == "/":
                self._send(200, PAGE_HTML.encode("utf-8"), "text/html; charset=utf-8")
            elif path == "/api/state":
                payload = build_state(db_path, repo, symbols)
                body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
                self._send(200, body, "application/json; charset=utf-8")
            else:
                self._send(404, b"not found", "text/plain; charset=utf-8")

        def log_message(self, format: str, *args: Any) -> None:
            log.debug("dashboard %s - %s", self.address_string(), format % args)

    return Handler


def serve(
    db_path: Path,
    repo: Path,
    symbols: list[str],
    *,
    host: str = "127.0.0.1",
    port: int = 8787,
    on_ready: Callable[[ThreadingHTTPServer], None] | None = None,
) -> None:
    """Serve the dashboard until interrupted (or until `server.shutdown()` from `on_ready`'s holder)."""
    server = ThreadingHTTPServer((host, port), _make_handler(Path(db_path), Path(repo), list(symbols)))
    server.daemon_threads = True
    if on_ready is not None:
        on_ready(server)
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        server.server_close()


PAGE_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ai_trader 实时面板</title>
<link rel="icon" href="data:,">
<style>
:root{--bg:#0d1117;--card:#161b22;--line:#30363d;--fg:#e6edf3;--mute:#8b949e;
--green:#3fb950;--red:#f85149;--amber:#d29922;--blue:#58a6ff}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:13px/1.45 -apple-system,"Segoe UI","Microsoft YaHei",
"PingFang SC",sans-serif}
header{position:sticky;top:0;z-index:5;background:#0d1117ee;border-bottom:1px solid var(--line);
padding:10px 16px;display:flex;flex-wrap:wrap;gap:10px 18px;align-items:center}
header h1{font-size:16px;margin:0 6px 0 0;font-weight:600}
.pill{display:inline-block;padding:2px 10px;border-radius:999px;font-weight:600;font-size:12px;
border:1px solid transparent}
.pill.g{background:#23863633;color:var(--green);border-color:#2386366e}
.pill.r{background:#da363333;color:var(--red);border-color:#da36336e}
.pill.a{background:#9e6a0333;color:var(--amber);border-color:#9e6a036e}
.pill.m{background:#30363d;color:var(--mute)}
.kv{color:var(--mute)} .kv b{color:var(--fg);font-variant-numeric:tabular-nums}
.pos{color:var(--green)!important} .neg{color:var(--red)!important}
#err{display:none;background:#da363322;border:1px solid var(--red);color:var(--red);margin:10px 16px 0;
padding:8px 12px;border-radius:6px}
main{padding:12px 16px;display:grid;gap:12px;grid-template-columns:repeat(auto-fill,minmax(420px,1fr))}
@media (max-width:520px){main{grid-template-columns:1fr;padding:10px}}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 12px;min-width:0}
.card h2{font-size:13px;margin:0 0 8px;color:var(--mute);font-weight:600;display:flex;justify-content:space-between}
.card.wide{grid-column:1/-1}
.sparks{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(300px,1fr))}
.spark .top{display:flex;justify-content:space-between;align-items:baseline}
.spark .px{font-size:18px;font-weight:600;font-variant-numeric:tabular-nums}
.spark canvas{width:100%;height:90px;display:block}
.tbl{overflow-x:auto;max-height:340px;overflow-y:auto}
table{border-collapse:collapse;width:100%;font-size:12px}
th,td{padding:3px 6px;border-bottom:1px solid #21262d;text-align:left;white-space:nowrap}
th{color:var(--mute);font-weight:500;position:sticky;top:0;background:var(--card)}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
td.wrap{white-space:normal;min-width:160px}
.empty{color:var(--mute);padding:6px 0}
.secerr{color:var(--red)}
.bars{display:flex;align-items:flex-end;gap:2px;height:110px;padding-top:6px}
.bars div{flex:1;background:var(--blue);min-height:1px;border-radius:2px 2px 0 0;opacity:.85}
.bars div:hover{opacity:1}
.axis{display:flex;justify-content:space-between;color:var(--mute);font-size:11px;margin-top:3px}
pre{margin:0;white-space:pre-wrap;word-break:break-all;font:11px/1.4 Consolas,monospace;color:var(--mute)}
footer{color:var(--mute);text-align:center;padding:10px 0 18px;font-size:12px}
</style>
</head>
<body>
<header>
  <h1>ai_trader 实时面板</h1>
  <span id="proc" class="pill m">加载中…</span>
  <span id="kill" class="pill m">杀开关 ?</span>
  <span id="stopreq"></span>
  <span class="kv">钱包 <b id="wallet">-</b></span>
  <span class="kv">今日盈亏(毛) <b id="pnlToday">-</b></span>
  <span class="kv">累计盈亏(毛) <b id="pnlTotal">-</b></span>
  <span class="kv">更新于 <b id="updated">-</b></span>
</header>
<div id="err"></div>
<main>
  <section class="card wide"><h2>行情（近 2 小时标记价）</h2><div class="sparks" id="sparks"></div></section>
  <section class="card"><h2>持仓与挂单</h2><div id="account"></div></section>
  <section class="card"><h2>数据计数 <span id="pidinfo"></span></h2><div id="counts"></div></section>
  <section class="card wide"><h2>最近信号</h2><div class="tbl" id="signals"></div></section>
  <section class="card wide"><h2>最近决策（含风控拒绝原因）</h2><div class="tbl" id="decisions"></div></section>
  <section class="card"><h2>最近成交</h2><div class="tbl" id="fills"></div></section>
  <section class="card"><h2>最近订单</h2><div class="tbl" id="orders"></div></section>
  <section class="card"><h2>信号有效性</h2><div class="tbl" id="eff"></div></section>
  <section class="card"><h2>每小时新闻量（近 24 小时）</h2><div id="news"></div></section>
  <section class="card"><h2>自动调参记录</h2><div class="tbl" id="tuning"></div></section>
  <section class="card"><h2>当前生效参数</h2><div class="tbl" id="params"></div></section>
  <section class="card wide"><h2>守护进程日志（末尾）</h2><pre id="logtail"></pre></section>
</main>
<footer>每 5 秒自动刷新 · 只读</footer>
<script>
"use strict";
const $ = id => document.getElementById(id);
const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const isErr = s => s && typeof s === "object" && !Array.isArray(s) && "error" in s;
const errHtml = s => `<div class="secerr">读取失败：${esc(s.error)}</div>`;
function tm(iso){ if(!iso) return "-"; const d=new Date(iso); if(isNaN(d)) return esc(iso);
  const p=n=>String(n).padStart(2,"0"); return `${p(d.getMonth()+1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`; }
function num(v, dp=2){ if(v===null||v===undefined) return "-"; const x=Number(v); if(!isFinite(x)) return esc(v);
  return x.toLocaleString("en-US",{minimumFractionDigits:dp,maximumFractionDigits:dp}); }
function price(v){ if(v===null||v===undefined) return "-"; const x=Number(v); return num(x, x>=1000?2:(x>=1?4:6)); }
function signed(v, dp=2){ if(v===null||v===undefined) return "-"; const x=Number(v);
  return `<span class="${x>0?"pos":x<0?"neg":""}">${x>0?"+":""}${num(x,dp)}</span>`; }
function pct(v, dp=2){ if(v===null||v===undefined) return "-"; return (Number(v)*100).toFixed(dp)+"%"; }
function age(s){ if(s===null||s===undefined) return "无数据"; if(s<90) return `${Math.round(s)} 秒前`;
  if(s<5400) return `${Math.round(s/60)} 分钟前`; return `${(s/3600).toFixed(1)} 小时前`; }
function table(rows, cols){
  if(isErr(rows)) return errHtml(rows);
  if(!rows || !rows.length) return `<div class="empty">暂无数据</div>`;
  const head = cols.map(c=>`<th class="${c[2]||""}">${esc(c[0])}</th>`).join("");
  const body = rows.map(r=>"<tr>"+cols.map(c=>{const v=c[1](r); return `<td class="${c[2]||""}">${v}</td>`;}).join("")+"</tr>").join("");
  return `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}
const dirTxt = d => d==="bullish"?'<span class="pos">看多</span>':d==="bearish"?'<span class="neg">看空</span>':esc(d);
const sideTxt = s => s==="BUY"||s==="LONG"?`<span class="pos">${esc(s)}</span>`:s==="SELL"||s==="SHORT"?`<span class="neg">${esc(s)}</span>`:esc(s);

function drawSpark(canvas, pts){
  const dpr = window.devicePixelRatio || 1, w = canvas.clientWidth, h = canvas.clientHeight;
  canvas.width = Math.max(1, w*dpr); canvas.height = Math.max(1, h*dpr);
  const ctx = canvas.getContext("2d"); ctx.scale(dpr, dpr); ctx.clearRect(0,0,w,h);
  if(!pts || pts.length < 2){ ctx.fillStyle="#8b949e"; ctx.font="12px sans-serif"; ctx.fillText("近 2 小时无足够样本", 8, h/2); return; }
  const ys = pts.map(p=>p[1]), xs = pts.map(p=>new Date(p[0]).getTime());
  let lo=Math.min(...ys), hi=Math.max(...ys); if(hi===lo){hi+=1; lo-=1;}
  const x0=xs[0], x1=xs[xs.length-1]||x0+1, pad=4, lw=w-2*pad, lh=h-2*pad-12;
  const X = t => pad + (x1===x0?lw:(t-x0)/(x1-x0)*lw), Y = v => pad + 12 + (hi-v)/(hi-lo)*lh;
  const up = ys[ys.length-1] >= ys[0], col = up ? "#3fb950" : "#f85149";
  const g = ctx.createLinearGradient(0,0,0,h); g.addColorStop(0, up?"#3fb95040":"#f8514940"); g.addColorStop(1,"#00000000");
  ctx.beginPath(); pts.forEach((p,i)=>{ const x=X(xs[i]), y=Y(p[1]); i?ctx.lineTo(x,y):ctx.moveTo(x,y); });
  ctx.strokeStyle=col; ctx.lineWidth=1.5; ctx.stroke();
  ctx.lineTo(X(x1), h); ctx.lineTo(X(x0), h); ctx.closePath(); ctx.fillStyle=g; ctx.fill();
  ctx.fillStyle="#8b949e"; ctx.font="10px sans-serif";
  ctx.fillText("高 "+price(hi), pad, 10); const lt="低 "+price(lo); ctx.fillText(lt, w-pad-ctx.measureText(lt).width, 10);
}

function render(s){
  // header
  const fr = isErr(s.freshness) ? {} : (s.freshness || {});
  const ages = Object.values(fr).map(f=>f.age_s).filter(a=>a!==null&&a!==undefined);
  const maxAge = ages.length ? Math.max(...ages) : null;
  const proc = isErr(s.process) ? null : s.process;
  const pe = $("proc");
  if(!proc){ pe.className="pill a"; pe.textContent="进程状态未知"; }
  else if(!proc.alive){ pe.className="pill r"; pe.textContent="已停止"; }
  else if(maxAge===null || maxAge>60){ pe.className="pill r"; pe.textContent="数据陈旧" + (maxAge!==null?`（${Math.round(maxAge)} 秒）`:""); }
  else { pe.className="pill g"; pe.textContent="运行中"; }
  $("pidinfo").textContent = proc ? `PID ${proc.pid ?? "-"}` : "";
  const ke = $("kill");
  if(isErr(s.kill_switch)){ ke.className="pill a"; ke.textContent="杀开关 ?"; }
  else if(s.kill_switch){ ke.className="pill r"; ke.textContent="杀开关 已触发"; }
  else { ke.className="pill g"; ke.textContent="杀开关 未触发"; }
  $("stopreq").innerHTML = s.stop_requested===true ? '<span class="pill a">已请求停止</span>' : "";
  const acc = isErr(s.account) ? null : s.account;
  $("wallet").textContent = acc ? num(acc.wallet)+" USDT" : "-";
  const pnl = isErr(s.pnl) ? null : s.pnl;
  $("pnlToday").innerHTML = pnl ? signed(pnl.today_gross, 4) : "-";
  $("pnlTotal").innerHTML = pnl ? signed(pnl.total_gross, 4) : "-";
  $("updated").textContent = tm(s.now_utc);

  // sparklines
  const sp = $("sparks"), marks = isErr(s.marks) ? {} : (s.marks || {});
  const syms = s.symbols || Object.keys(marks);
  if(sp.dataset.syms !== syms.join(",")){
    sp.innerHTML = syms.map(sym=>`<div class="spark"><div class="top"><b>${esc(sym)}</b><span><span class="px" id="px-${esc(sym)}">-</span> <span class="kv" id="age-${esc(sym)}"></span></span></div><canvas id="cv-${esc(sym)}"></canvas></div>`).join("");
    sp.dataset.syms = syms.join(",");
  }
  syms.forEach(sym=>{
    const f = fr[sym] || {};
    $("px-"+sym).textContent = price(f.price);
    const a = $("age-"+sym); a.textContent = age(f.age_s); a.className = "kv " + ((f.age_s===null||f.age_s===undefined||f.age_s>60)?"neg":"");
    drawSpark($("cv-"+sym), marks[sym]);
  });
  if(isErr(s.marks)) sp.insertAdjacentHTML("beforeend", errHtml(s.marks));

  // account
  if(isErr(s.account)) $("account").innerHTML = errHtml(s.account);
  else if(!acc) $("account").innerHTML = '<div class="empty">尚无持久化的模拟账户（paper 交易后出现）</div>';
  else $("account").innerHTML =
    `<div class="kv" style="margin-bottom:6px">钱包 <b>${num(acc.wallet)}</b> · 已实现(净) ${signed(acc.realized_pnl,4)}</div>` +
    table(acc.positions, [["品种",r=>esc(r.symbol)],["方向",r=>sideTxt(r.side)],["数量",r=>num(r.qty,4),"n"],
      ["开仓价",r=>price(r.entry_price),"n"],["标记价",r=>price(r.mark_price),"n"],["浮盈",r=>signed(r.unrealized_pnl,4),"n"]]) +
    `<div class="kv" style="margin:8px 0 4px">挂单（${acc.resting_orders.length}）</div>` +
    table(acc.resting_orders, [["品种",r=>esc(r.symbol)],["方向",r=>sideTxt(r.side)],["类型",r=>esc(r.type)],
      ["触发价",r=>price(r.stop_price),"n"],["订单号",r=>esc(r.order_id)]]);

  // counts
  if(isErr(s.counts)) $("counts").innerHTML = errHtml(s.counts);
  else $("counts").innerHTML = table(Object.entries(s.counts||{}).map(([k,v])=>({k,v})), [["表",r=>esc(r.k)],["行数",r=>r.v===null?"-":num(r.v,0),"n"]]);

  $("signals").innerHTML = table(s.signals, [["时间",r=>tm(r.ts)],["探测器",r=>esc(r.detector)],["品种",r=>esc(r.symbol)],
    ["方向",r=>dirTxt(r.direction)],["强度",r=>num(r.strength,2),"n"],["理由",r=>esc(r.rationale),"wrap"]]);
  $("decisions").innerHTML = table(s.decisions, [["时间",r=>tm(r.ts)],["品种",r=>esc(r.symbol)],["方向",r=>sideTxt(r.side)],
    ["意图",r=>esc(r.intent)],["名义",r=>num(r.notional_usdt),"n"],["得分",r=>num(r.score,2),"n"],
    ["风控",r=>r.approved===null?'<span class="kv">无</span>':r.approved?'<span class="pos">通过</span>':'<span class="neg">拒绝</span>'],
    ["调整后",r=>r.adjusted===null?"-":num(r.adjusted),"n"],["原因",r=>esc(r.reason||""),"wrap"]]);
  $("fills").innerHTML = table(s.fills, [["时间",r=>tm(r.ts)],["品种",r=>esc(r.symbol)],["方向",r=>sideTxt(r.side)],
    ["价格",r=>price(r.price),"n"],["数量",r=>num(r.qty,4),"n"],["已实现",r=>signed(r.realized_pnl,4),"n"],["手续费",r=>num(r.commission,4),"n"]]);
  $("orders").innerHTML = table(s.orders, [["更新",r=>tm(r.ts)],["品种",r=>esc(r.symbol)],["方向",r=>sideTxt(r.side)],
    ["角色",r=>esc(r.role)],["类型",r=>esc(r.type)],["状态",r=>esc(r.status)],["均价",r=>price(r.avg_price),"n"],["成交量",r=>num(r.executed_qty,4),"n"]]);
  $("eff").innerHTML = table(s.effectiveness, [["探测器",r=>esc(r.detector)],["窗口(s)",r=>esc(r.horizon_s),"n"],["样本",r=>num(r.n,0),"n"],
    ["均值收益",r=>`<span class="${r.mean_ret>0?"pos":r.mean_ret<0?"neg":""}">${pct(r.mean_ret,3)}</span>`,"n"],["命中率",r=>pct(r.hit_rate,1),"n"]]);
  $("tuning").innerHTML = table(s.tuning_log, [["时间",r=>tm(r.ts)],["规则",r=>esc(r.rule)],["字段",r=>esc(r.field)],
    ["旧值",r=>esc(r.old),"n"],["新值",r=>esc(r.new),"n"],["原因",r=>esc(r.reason),"wrap"]]);

  // effective params (flatten nested JSON)
  const ep = s.effective_params;
  if(isErr(ep)) $("params").innerHTML = errHtml(ep);
  else if(!ep) $("params").innerHTML = '<div class="empty">运行中的进程尚未发布生效参数</div>';
  else { const flat=[]; (function walk(o,p){ for(const [k,v] of Object.entries(o)){ const key=p?p+"."+k:k;
      if(v && typeof v==="object" && !Array.isArray(v)) walk(v,key); else flat.push({k:key,v}); } })(ep,"");
    $("params").innerHTML = table(flat, [["参数",r=>esc(r.k)],["值",r=>esc(typeof r.v==="string"&&r.k==="ts"?tm(r.v):r.v),"n"]]); }

  // news bars
  const nh = s.news_per_hour;
  if(isErr(nh)) $("news").innerHTML = errHtml(nh);
  else if(!nh || !nh.length) $("news").innerHTML = '<div class="empty">暂无数据</div>';
  else { const mx = Math.max(1, ...nh.map(b=>b.n)), tot = nh.reduce((a,b)=>a+b.n,0);
    const hh = iso => String(new Date(iso).getHours()).padStart(2,"0")+":00";
    $("news").innerHTML = `<div class="kv">合计 <b>${tot}</b> 条 · 峰值 <b>${mx}</b>/小时</div><div class="bars">` +
      nh.map(b=>`<div style="height:${(b.n/mx*100).toFixed(1)}%" title="${esc(hh(b.hour))}  ${b.n} 条"></div>`).join("") +
      `</div><div class="axis"><span>${hh(nh[0].hour)}</span><span>${hh(nh[Math.floor(nh.length/2)].hour)}</span><span>${hh(nh[nh.length-1].hour)}</span></div>`; }

  const lt = proc && proc.log_tail ? proc.log_tail : [];
  $("logtail").textContent = (proc && proc.log_tail_source ? proc.log_tail_source + "\n" : "") + (lt.length ? lt.join("\n") : "（无日志）");
}

let last = null;
async function tick(){
  try{
    const r = await fetch("/api/state", {cache:"no-store"});
    if(!r.ok) throw new Error("HTTP " + r.status);
    last = await r.json(); render(last); $("err").style.display = "none";
  }catch(e){
    const el = $("err"); el.style.display = "block";
    el.textContent = "刷新失败：" + e.message + "（面板服务可能已停止；显示的是上次成功获取的数据）";
  }
}
tick(); setInterval(tick, 5000);
window.addEventListener("resize", ()=>{ if(last) render(last); });
</script>
</body>
</html>
"""
