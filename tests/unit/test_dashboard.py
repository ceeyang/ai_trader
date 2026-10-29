import asyncio
import json
import os
import sqlite3
import threading
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from conftest import make_decision, make_fill, make_mark_price, make_news, make_order_record, make_signal

from ai_trader import dashboard
from ai_trader.dashboard import TABLES, build_state, serve
from ai_trader.models import (
    OrderRequest,
    OrderRole,
    OrderStatus,
    OrderType,
    RiskVerdict,
    Side,
    TuningChange,
)
from ai_trader.storage.db import Store

SYMBOLS = ["BTCUSDT", "ETHUSDT"]

EXPECTED_KEYS = {
    "now_utc",
    "process",
    "freshness",
    "counts",
    "account",
    "kill_switch",
    "stop_requested",
    "effective_params",
    "pnl",
    "marks",
    "signals",
    "decisions",
    "orders",
    "fills",
    "effectiveness",
    "tuning_log",
    "news_per_hour",
}


def _paper_state() -> str:
    """A minimal snapshot in `PaperBroker._snapshot()`'s format."""
    stop = OrderRequest(
        symbol="BTCUSDT",
        side=Side.SELL,
        type=OrderType.STOP_MARKET,
        stop_price=Decimal(79000),
        close_position=True,
        client_order_id="sl-1",
    )
    return json.dumps(
        {
            "version": 1,
            "wallet_balance": "9990.5",
            "realized_pnl": "-9.5",
            "next_order_id": 7,
            "positions": {"BTCUSDT": {"qty": "0.002", "entry_price": "80000"}},
            "pending": [{"order_id": 5, "request": stop.model_dump(mode="json")}],
        }
    )


@pytest.fixture
async def seeded(tmp_path):
    now = datetime.now(UTC)
    db_path = tmp_path / "data" / "ai_trader.db"
    store = Store(db_path)
    await store.open()
    # 300 BTC samples over the last ~100 min (more than the 240-point cap), latest 5 s old.
    base = make_mark_price(symbol="BTCUSDT").mark_price
    for i in range(300):
        ts = now - timedelta(seconds=5 + (299 - i) * 20)
        await store.insert_mark_sample("BTCUSDT", ts, base + i)
    await store.insert_mark_sample("BTCUSDT", now - timedelta(hours=3), Decimal(1))  # outside window
    await store.insert_mark_sample("ETHUSDT", now - timedelta(seconds=30), Decimal("3000.5"))

    for i in range(35):
        await store.insert_signal(make_signal(f"s{i}", created_at=now - timedelta(minutes=i)))
    await store.insert_forward_return("s1", 300, 0.01)
    await store.insert_forward_return("s2", 300, -0.02)

    approved = make_decision().model_copy(update={"created_at": now - timedelta(minutes=2)})
    rejected = make_decision(symbol="ETHUSDT").model_copy(update={"created_at": now - timedelta(minutes=1)})
    await store.insert_decision(approved)
    await store.insert_decision(rejected)
    await store.insert_risk_verdict(approved.id, RiskVerdict(approved=True, adjusted_notional=Decimal(50)))
    await store.insert_risk_verdict(rejected.id, RiskVerdict(approved=False, reason="kill switch active"))

    await store.upsert_order(make_order_record("o1", role=OrderRole.ENTRY, status=OrderStatus.FILLED))
    await store.insert_fill(make_fill("o1", realized_pnl=Decimal("1.5"), event_time=now - timedelta(seconds=1)))
    await store.insert_fill(make_fill("o2", realized_pnl=Decimal(-4), event_time=now - timedelta(days=3)))

    await store.insert_news(make_news("n1"))
    await store.insert_tuning_change(
        TuningChange(ts=now, rule="entry_rate", field="strategy.entry_threshold", old="0.5", new="0.55", reason="r")
    )
    await store.set_kv("paper_state", _paper_state())
    await store.set_kv("tuning_effective", json.dumps({"ts": now.isoformat(), "strategy": {"cooldown_s": 300}}))
    await store.set_kv("kill_switch", "1")

    repo = tmp_path
    (repo / "data" / "paper-run.pid").write_text(str(os.getpid()))
    (repo / "data" / "paper-run.latest").write_text("20261029-000000")
    (repo / "data" / "paper-run-20261029-000000.log").write_text("")
    (repo / "data" / "paper-run-20261029-000000.err.log").write_text("err one\nerr two\n")
    yield db_path, repo
    await store.close()


async def test_build_state_has_every_section(seeded):
    db_path, repo = seeded
    s = build_state(db_path, repo, SYMBOLS)
    assert EXPECTED_KEYS <= s.keys()
    json.dumps(s)  # serialisable
    assert not [k for k in EXPECTED_KEYS if isinstance(s[k], dict) and "error" in s[k]]

    assert s["process"]["pid"] == os.getpid() and s["process"]["alive"] is True
    assert s["process"]["log"].endswith("paper-run-20261029-000000.log")
    assert s["process"]["log_tail"] == ["err one", "err two"]  # newest non-empty of .log / .err.log

    assert s["freshness"]["BTCUSDT"]["price"] == 80299.0
    assert 0 <= s["freshness"]["BTCUSDT"]["age_s"] < 60
    assert s["freshness"]["ETHUSDT"]["price"] == 3000.5

    assert set(s["counts"]) == set(TABLES)
    assert s["counts"]["signals"] == 35 and s["counts"]["mark_samples"] == 302
    assert s["counts"]["decisions"] == 2 and s["counts"]["fills"] == 2 and s["counts"]["news"] == 1

    acc = s["account"]
    assert acc["wallet"] == 9990.5 and acc["realized_pnl"] == -9.5
    (pos,) = acc["positions"]
    assert pos["symbol"] == "BTCUSDT" and pos["side"] == "LONG" and pos["qty"] == 0.002
    assert pos["mark_price"] == 80299.0 and pos["unrealized_pnl"] == pytest.approx(0.598)
    (order,) = acc["resting_orders"]
    assert order["type"] == "STOP_MARKET" and order["stop_price"] == 79000.0 and order["order_id"] == 5

    assert s["kill_switch"] is True and s["stop_requested"] is False
    assert s["effective_params"]["strategy"]["cooldown_s"] == 300
    assert s["pnl"] == {"today_gross": 1.5, "total_gross": -2.5} or (
        # just after UTC midnight the "today" fill may fall on the previous day
        s["pnl"]["total_gross"] == -2.5
    )

    btc = s["marks"]["BTCUSDT"]
    assert 2 <= len(btc) <= 240 and btc[-1][1] == 80299.0
    assert all(p[1] != 1.0 for p in btc)  # the 3 h old sample is outside the window
    assert s["marks"]["ETHUSDT"] == [[s["freshness"]["ETHUSDT"]["ts"], 3000.5]]

    assert len(s["signals"]) == 30 and s["signals"][0]["detector"] == "funding_extreme"
    assert len(s["signals"][0]["rationale"]) <= 80
    d0, d1 = s["decisions"]
    assert d0["symbol"] == "ETHUSDT" and d0["approved"] is False and d0["reason"] == "kill switch active"
    assert d1["approved"] is True and d1["adjusted"] == 50.0
    assert s["orders"][0]["client_order_id"] == "o1"
    assert [f["realized_pnl"] for f in s["fills"]] == [1.5, -4.0]
    (eff,) = s["effectiveness"]
    assert eff["n"] == 2 and eff["horizon_s"] == 300 and eff["hit_rate"] == 0.5
    assert s["tuning_log"][0]["field"] == "strategy.entry_threshold"
    assert len(s["news_per_hour"]) == 24  # make_news uses a fixed fetched_at; counts may be zero


async def test_section_error_does_not_break_payload(tmp_path):
    db_path = tmp_path / "partial.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT INTO kv VALUES ('paper_state', ?)", (_paper_state(),))
    conn.commit()
    conn.close()
    s = build_state(db_path, tmp_path, SYMBOLS)
    assert EXPECTED_KEYS <= s.keys()
    assert s["signals"] == {"error": "OperationalError"}
    assert s["freshness"] == {"error": "OperationalError"}
    assert s["account"]["wallet"] == 9990.5  # the kv-backed section still works
    assert s["counts"]["kv"] == 1 and s["counts"]["signals"] is None
    assert s["process"]["pid"] is None and s["process"]["alive"] is False and s["process"]["log_tail"] == []
    json.dumps(s)


async def test_monkeypatched_query_failure_is_isolated(seeded, monkeypatch):
    db_path, repo = seeded

    def boom(conn):
        raise RuntimeError("x")

    monkeypatch.setattr(dashboard, "_fills", boom)
    s = build_state(db_path, repo, SYMBOLS)
    assert s["fills"] == {"error": "RuntimeError"}
    assert len(s["signals"]) == 30


def test_missing_db_errors_every_db_section(tmp_path):
    s = build_state(tmp_path / "nope.db", tmp_path, SYMBOLS)
    assert s["counts"] == {"error": "FileNotFoundError"}
    assert not (tmp_path / "nope.db").exists()  # never created


async def test_serve_routes(seeded):
    db_path, repo = seeded
    holder: dict = {}
    ready = threading.Event()

    def on_ready(server):
        holder["server"] = server
        ready.set()

    t = threading.Thread(
        target=serve, args=(db_path, repo, SYMBOLS), kwargs={"port": 0, "on_ready": on_ready}, daemon=True
    )
    t.start()
    assert ready.wait(5)
    server = holder["server"]
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        await asyncio.to_thread(_exercise_routes, base)
    finally:
        server.shutdown()
        t.join(5)
    assert not t.is_alive()


def _exercise_routes(base: str) -> None:
    with urllib.request.urlopen(base + "/api/state", timeout=10) as r:
        assert r.status == 200
        assert r.headers["Content-Type"].startswith("application/json")
        assert "no-cache" in r.headers["Cache-Control"]
        body = json.loads(r.read().decode("utf-8"))
    assert "now_utc" in body
    with urllib.request.urlopen(base + "/", timeout=10) as r:
        assert r.status == 200 and r.headers["Content-Type"].startswith("text/html")
        assert "实时" in r.read().decode("utf-8")
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(base + "/nope", timeout=10)
    assert exc.value.code == 404
