"""Watchdog probe for the overnight paper run. Prints one JSON object; read-only."""

import json
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

repo = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
db = repo / "data" / "ai_trader.db"
pid_file = repo / "data" / "paper-run.pid"
out: dict = {"now_utc": datetime.now(UTC).isoformat(timespec="seconds")}

pid = pid_file.read_text().strip() if pid_file.exists() else None
out["pid"] = pid
alive = False
if pid:
    r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], check=False, capture_output=True, text=True)
    alive = pid in r.stdout
out["alive"] = alive

if db.exists():
    c = sqlite3.connect(str(db))
    counts = {}
    for t in ("mark_samples", "news", "sentiments", "signals", "decisions", "risk_verdicts", "orders", "fills", "tuning_log"):
        try:
            counts[t] = c.execute(f"select count(*) from {t}").fetchone()[0]
        except sqlite3.Error:
            counts[t] = None
    out["counts"] = counts
    row = c.execute("select max(ts) from mark_samples").fetchone()
    if row and row[0]:
        last = datetime.fromisoformat(row[0])
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        out["last_sample_age_s"] = round((datetime.now(UTC) - last).total_seconds(), 1)
    else:
        out["last_sample_age_s"] = None
    try:
        out["kill_switch"] = c.execute("select value from kv where key='kill_switch'").fetchone()
    except sqlite3.Error:
        out["kill_switch"] = None
    try:
        out["realized_pnl_total"] = c.execute("select coalesce(sum(cast(realized_pnl as real)),0) from fills").fetchone()[0]
    except sqlite3.Error:
        out["realized_pnl_total"] = None
    c.close()
else:
    out["counts"] = None

print(json.dumps(out, ensure_ascii=False))
