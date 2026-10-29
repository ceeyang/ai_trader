"""SQLite persistence layer on aiosqlite (design 5.10).

Datetimes are stored as ISO-8601 UTC strings (``isoformat()`` of tz-aware
values), ``Decimal`` values as TEXT via ``str()``, and lists/dicts as JSON
TEXT. Everything is read back into the matching pydantic model.
"""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import NamedTuple

import aiosqlite

from ai_trader.models import (
    Decision,
    Direction,
    Fill,
    NewsItem,
    OrderRecord,
    OrderRole,
    OrderStatus,
    OrderType,
    RiskVerdict,
    Sentiment,
    Side,
    Signal,
    TuningChange,
    new_id,
    utc_now,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS news (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    author TEXT,
    title TEXT NOT NULL,
    text TEXT NOT NULL,
    url TEXT,
    published_at TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    raw TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sentiments (
    id TEXT PRIMARY KEY,
    news_id TEXT NOT NULL REFERENCES news(id),
    direction TEXT NOT NULL,
    confidence REAL NOT NULL,
    symbols TEXT NOT NULL,
    horizon TEXT NOT NULL,
    rationale TEXT NOT NULL,
    model TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS signals (
    id TEXT PRIMARY KEY,
    detector TEXT NOT NULL,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    strength REAL NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    ref_price TEXT NOT NULL,
    rationale TEXT NOT NULL,
    meta TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS forward_returns (
    signal_id TEXT NOT NULL REFERENCES signals(id),
    horizon_s INTEGER NOT NULL,
    ret REAL,  -- NULL: unscorable (no mark sample near the horizon); never retried
    computed_at TEXT NOT NULL,
    PRIMARY KEY (signal_id, horizon_s)
);

CREATE TABLE IF NOT EXISTS mark_samples (
    symbol TEXT NOT NULL,
    ts TEXT NOT NULL,
    price TEXT NOT NULL,
    PRIMARY KEY (symbol, ts)
);

CREATE TABLE IF NOT EXISTS decisions (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    intent TEXT NOT NULL,
    notional_usdt TEXT NOT NULL,
    score REAL NOT NULL,
    signal_ids TEXT NOT NULL,
    created_at TEXT NOT NULL,
    stop_loss_pct TEXT NOT NULL,
    take_profit_pct TEXT NOT NULL,
    max_hold_s INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS risk_verdicts (
    id TEXT PRIMARY KEY,
    decision_id TEXT NOT NULL REFERENCES decisions(id),
    approved INTEGER NOT NULL,
    reason TEXT,
    adjusted_notional TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    client_order_id TEXT PRIMARY KEY,
    decision_id TEXT,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    type TEXT NOT NULL,
    role TEXT NOT NULL,
    qty TEXT,
    price TEXT,
    stop_price TEXT,
    reduce_only INTEGER NOT NULL,
    close_position INTEGER NOT NULL,
    status TEXT NOT NULL,
    order_id INTEGER,
    avg_price TEXT NOT NULL,
    executed_qty TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fills (
    order_id INTEGER NOT NULL,
    client_order_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    price TEXT NOT NULL,
    qty TEXT NOT NULL,
    realized_pnl TEXT NOT NULL,
    commission TEXT NOT NULL,
    event_time TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tuning_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    rule TEXT NOT NULL,
    field TEXT NOT NULL,
    old TEXT NOT NULL,
    new TEXT NOT NULL,
    reason TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_signals_created_at ON signals(created_at);
CREATE INDEX IF NOT EXISTS idx_decisions_created_at ON decisions(created_at);
"""

async def _migrate_forward_returns_nullable(db: aiosqlite.Connection) -> None:
    """Databases created before `forward_returns.ret` became nullable: rebuild the table."""
    cur = await db.execute("PRAGMA table_info(forward_returns)")
    cols = {row[1]: row for row in await cur.fetchall()}
    if not cols["ret"][3]:  # notnull flag
        return
    await db.executescript(
        """
        ALTER TABLE forward_returns RENAME TO forward_returns_old;
        CREATE TABLE forward_returns (
            signal_id TEXT NOT NULL REFERENCES signals(id),
            horizon_s INTEGER NOT NULL,
            ret REAL,
            computed_at TEXT NOT NULL,
            PRIMARY KEY (signal_id, horizon_s)
        );
        INSERT INTO forward_returns SELECT signal_id, horizon_s, ret, computed_at FROM forward_returns_old;
        DROP TABLE forward_returns_old;
        """
    )


_TABLES = frozenset(
    {
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
    }
)


class EffectivenessRow(NamedTuple):
    detector: str
    horizon_s: int
    n: int
    mean_ret: float
    hit_rate: float


def _signal_from_row(row: aiosqlite.Row) -> Signal:
    return Signal(
        id=row["id"],
        detector=row["detector"],
        symbol=row["symbol"],
        direction=Direction(row["direction"]),
        strength=row["strength"],
        created_at=datetime.fromisoformat(row["created_at"]),
        expires_at=datetime.fromisoformat(row["expires_at"]),
        ref_price=Decimal(row["ref_price"]),
        rationale=row["rationale"],
        meta=json.loads(row["meta"]),
    )


def _order_from_row(row: aiosqlite.Row) -> OrderRecord:
    return OrderRecord(
        client_order_id=row["client_order_id"],
        decision_id=row["decision_id"],
        symbol=row["symbol"],
        side=Side(row["side"]),
        type=OrderType(row["type"]),
        role=OrderRole(row["role"]),
        qty=Decimal(row["qty"]) if row["qty"] is not None else None,
        price=Decimal(row["price"]) if row["price"] is not None else None,
        stop_price=Decimal(row["stop_price"]) if row["stop_price"] is not None else None,
        reduce_only=bool(row["reduce_only"]),
        close_position=bool(row["close_position"]),
        status=OrderStatus(row["status"]),
        order_id=row["order_id"],
        avg_price=Decimal(row["avg_price"]),
        executed_qty=Decimal(row["executed_qty"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


class Store:
    """SQLite-backed persistence for news/signals/orders/fills (design 5.10)."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._db: aiosqlite.Connection | None = None

    async def open(self) -> None:
        if self._db is not None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        db = await aiosqlite.connect(self._path)
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA foreign_keys=ON")
        await db.executescript(_SCHEMA)
        await _migrate_forward_returns_nullable(db)
        await db.commit()
        self._db = db

    async def close(self) -> None:
        if self._db is None:
            return
        await self._db.close()
        self._db = None

    @property
    def _conn(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Store is not open; call open() first")
        return self._db

    # ---- news ---------------------------------------------------------

    async def news_exists(self, news_id: str) -> bool:
        cur = await self._conn.execute("SELECT 1 FROM news WHERE id = ?", (news_id,))
        return await cur.fetchone() is not None

    async def insert_news(self, item: NewsItem) -> bool:
        cur = await self._conn.execute(
            "INSERT OR IGNORE INTO news "
            "(id, source, author, title, text, url, published_at, fetched_at, raw) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                item.id,
                item.source,
                item.author,
                item.title,
                item.text,
                item.url,
                item.published_at.isoformat(),
                item.fetched_at.isoformat(),
                json.dumps(item.raw),
            ),
        )
        await self._conn.commit()
        return cur.rowcount > 0

    # ---- sentiments -----------------------------------------------------

    async def insert_sentiment(self, news_id: str, sentiment: Sentiment) -> None:
        await self._conn.execute(
            "INSERT INTO sentiments "
            "(id, news_id, direction, confidence, symbols, horizon, rationale, model, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                new_id(),
                news_id,
                sentiment.direction.value,
                sentiment.confidence,
                json.dumps(sentiment.symbols),
                sentiment.horizon.value,
                sentiment.rationale,
                sentiment.model,
                utc_now().isoformat(),
            ),
        )
        await self._conn.commit()

    # ---- signals / forward returns -------------------------------------

    async def insert_signal(self, signal: Signal) -> None:
        await self._conn.execute(
            "INSERT INTO signals "
            "(id, detector, symbol, direction, strength, created_at, expires_at, ref_price, "
            "rationale, meta) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                signal.id,
                signal.detector,
                signal.symbol,
                signal.direction.value,
                signal.strength,
                signal.created_at.isoformat(),
                signal.expires_at.isoformat(),
                str(signal.ref_price),
                signal.rationale,
                json.dumps(signal.meta),
            ),
        )
        await self._conn.commit()

    async def recent_signals(self, limit: int) -> list[Signal]:
        cur = await self._conn.execute(
            "SELECT * FROM signals ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        rows = await cur.fetchall()
        return [_signal_from_row(r) for r in rows]

    async def signals_missing_forward_return(self, horizon_s: int, before: datetime) -> list[Signal]:
        cur = await self._conn.execute(
            "SELECT s.* FROM signals s LEFT JOIN forward_returns fr "
            "ON fr.signal_id = s.id AND fr.horizon_s = ? "
            "WHERE fr.signal_id IS NULL ORDER BY s.created_at",
            (horizon_s,),
        )
        rows = await cur.fetchall()
        out = []
        for row in rows:
            created_at = datetime.fromisoformat(row["created_at"])
            if created_at + timedelta(seconds=horizon_s) <= before:
                out.append(_signal_from_row(row))
        return out

    async def insert_forward_return(self, signal_id: str, horizon_s: int, ret: float | None) -> None:
        """`ret=None` records the signal as unscorable for this horizon: it is no longer
        returned by `signals_missing_forward_return` and is excluded from `effectiveness`."""
        await self._conn.execute(
            "INSERT OR REPLACE INTO forward_returns (signal_id, horizon_s, ret, computed_at) "
            "VALUES (?, ?, ?, ?)",
            (signal_id, horizon_s, ret, utc_now().isoformat()),
        )
        await self._conn.commit()

    async def effectiveness(self) -> list[EffectivenessRow]:
        cur = await self._conn.execute(
            "SELECT s.detector AS detector, fr.horizon_s AS horizon_s, COUNT(*) AS n, "
            "AVG(fr.ret) AS mean_ret, AVG(fr.ret > 0) AS hit_rate "
            "FROM forward_returns fr JOIN signals s ON s.id = fr.signal_id "
            "WHERE fr.ret IS NOT NULL "
            "GROUP BY s.detector, fr.horizon_s"
        )
        rows = await cur.fetchall()
        return [
            EffectivenessRow(
                detector=r["detector"],
                horizon_s=r["horizon_s"],
                n=r["n"],
                mean_ret=r["mean_ret"],
                hit_rate=r["hit_rate"],
            )
            for r in rows
        ]

    # ---- mark samples ----------------------------------------------------

    async def insert_mark_sample(self, symbol: str, ts: datetime, price: Decimal) -> None:
        await self._conn.execute(
            "INSERT OR REPLACE INTO mark_samples (symbol, ts, price) VALUES (?, ?, ?)",
            (symbol, ts.isoformat(), str(price)),
        )
        await self._conn.commit()

    async def mark_at(self, symbol: str, ts: datetime, tolerance_s: int = 60) -> Decimal | None:
        # Bounded scan. Samples are stored as UTC ISO strings, which sort chronologically;
        # the window is widened by a second and re-checked exactly below.
        lo = (ts - timedelta(seconds=tolerance_s + 1)).astimezone(UTC).isoformat()
        hi = (ts + timedelta(seconds=tolerance_s + 1)).astimezone(UTC).isoformat()
        cur = await self._conn.execute(
            "SELECT ts, price FROM mark_samples WHERE symbol = ? AND ts BETWEEN ? AND ?",
            (symbol, lo, hi),
        )
        rows = await cur.fetchall()
        best_price: str | None = None
        best_diff: float | None = None
        for row in rows:
            diff = abs((ts - datetime.fromisoformat(row["ts"])).total_seconds())
            if diff <= tolerance_s and (best_diff is None or diff < best_diff):
                best_price, best_diff = row["price"], diff
        return Decimal(best_price) if best_price is not None else None

    # ---- decisions / risk verdicts ---------------------------------------

    async def insert_decision(self, decision: Decision) -> None:
        await self._conn.execute(
            "INSERT INTO decisions "
            "(id, symbol, side, intent, notional_usdt, score, signal_ids, created_at, "
            "stop_loss_pct, take_profit_pct, max_hold_s) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                decision.id,
                decision.symbol,
                decision.side.value,
                decision.intent.value,
                str(decision.notional_usdt),
                decision.score,
                json.dumps(decision.signal_ids),
                decision.created_at.isoformat(),
                str(decision.stop_loss_pct),
                str(decision.take_profit_pct),
                decision.max_hold_s,
            ),
        )
        await self._conn.commit()

    async def insert_risk_verdict(self, decision_id: str, verdict: RiskVerdict) -> None:
        await self._conn.execute(
            "INSERT INTO risk_verdicts (id, decision_id, approved, reason, adjusted_notional, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                new_id(),
                decision_id,
                int(verdict.approved),
                verdict.reason,
                str(verdict.adjusted_notional) if verdict.adjusted_notional is not None else None,
                utc_now().isoformat(),
            ),
        )
        await self._conn.commit()

    async def last_decision_at(self, symbol: str) -> datetime | None:
        cur = await self._conn.execute(
            "SELECT created_at FROM decisions WHERE symbol = ? ORDER BY created_at DESC LIMIT 1",
            (symbol,),
        )
        row = await cur.fetchone()
        return datetime.fromisoformat(row["created_at"]) if row else None

    # ---- orders ------------------------------------------------------

    async def upsert_order(self, record: OrderRecord) -> None:
        await self._conn.execute(
            "INSERT INTO orders "
            "(client_order_id, decision_id, symbol, side, type, role, qty, price, stop_price, "
            "reduce_only, close_position, status, order_id, avg_price, executed_qty, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(client_order_id) DO UPDATE SET "
            "decision_id=excluded.decision_id, symbol=excluded.symbol, side=excluded.side, "
            "type=excluded.type, role=excluded.role, qty=excluded.qty, price=excluded.price, "
            "stop_price=excluded.stop_price, reduce_only=excluded.reduce_only, "
            "close_position=excluded.close_position, status=excluded.status, "
            "order_id=excluded.order_id, avg_price=excluded.avg_price, "
            "executed_qty=excluded.executed_qty, created_at=excluded.created_at, "
            "updated_at=excluded.updated_at",
            (
                record.client_order_id,
                record.decision_id,
                record.symbol,
                record.side.value,
                record.type.value,
                record.role.value,
                str(record.qty) if record.qty is not None else None,
                str(record.price) if record.price is not None else None,
                str(record.stop_price) if record.stop_price is not None else None,
                int(record.reduce_only),
                int(record.close_position),
                record.status.value,
                record.order_id,
                str(record.avg_price),
                str(record.executed_qty),
                record.created_at.isoformat(),
                record.updated_at.isoformat(),
            ),
        )
        await self._conn.commit()

    async def get_order(self, client_order_id: str) -> OrderRecord | None:
        cur = await self._conn.execute(
            "SELECT * FROM orders WHERE client_order_id = ?", (client_order_id,)
        )
        row = await cur.fetchone()
        return _order_from_row(row) if row else None

    async def open_protective_orders(self, symbol: str) -> list[OrderRecord]:
        cur = await self._conn.execute(
            "SELECT * FROM orders WHERE symbol = ? AND role IN ('stop_loss','take_profit') "
            "AND status IN ('NEW','PARTIALLY_FILLED')",
            (symbol,),
        )
        rows = await cur.fetchall()
        return [_order_from_row(r) for r in rows]

    async def symbols_with_open_protective_orders(self) -> list[str]:
        cur = await self._conn.execute(
            "SELECT DISTINCT symbol FROM orders WHERE role IN ('stop_loss','take_profit') "
            "AND status IN ('NEW','PARTIALLY_FILLED') ORDER BY symbol"
        )
        rows = await cur.fetchall()
        return [r["symbol"] for r in rows]

    async def update_order_status(
        self,
        client_order_id: str,
        status: OrderStatus,
        executed_qty: Decimal,
        avg_price: Decimal,
        order_id: int,
    ) -> None:
        await self._conn.execute(
            "UPDATE orders SET status = ?, executed_qty = ?, avg_price = ?, order_id = ?, "
            "updated_at = ? WHERE client_order_id = ?",
            (
                status.value,
                str(executed_qty),
                str(avg_price),
                order_id,
                utc_now().isoformat(),
                client_order_id,
            ),
        )
        await self._conn.commit()

    # ---- fills ------------------------------------------------------

    async def insert_fill(self, fill: Fill) -> None:
        await self._conn.execute(
            "INSERT INTO fills "
            "(order_id, client_order_id, symbol, side, price, qty, realized_pnl, commission, "
            "event_time) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                fill.order_id,
                fill.client_order_id,
                fill.symbol,
                fill.side.value,
                str(fill.price),
                str(fill.qty),
                str(fill.realized_pnl),
                str(fill.commission),
                fill.event_time.isoformat(),
            ),
        )
        await self._conn.commit()

    async def realized_pnl_since(self, since: datetime) -> Decimal:
        cur = await self._conn.execute(
            "SELECT realized_pnl FROM fills WHERE event_time >= ?", (since.isoformat(),)
        )
        rows = await cur.fetchall()
        return sum((Decimal(r["realized_pnl"]) for r in rows), Decimal(0))

    async def consecutive_losses(self) -> int:
        cur = await self._conn.execute(
            "SELECT realized_pnl FROM fills WHERE CAST(realized_pnl AS REAL) != 0 ORDER BY event_time DESC"
        )
        rows = await cur.fetchall()
        count = 0
        for row in rows:
            if Decimal(row["realized_pnl"]) >= 0:
                break
            count += 1
        return count

    # ---- kv ------------------------------------------------------

    async def get_kv(self, key: str) -> str | None:
        cur = await self._conn.execute("SELECT value FROM kv WHERE key = ?", (key,))
        row = await cur.fetchone()
        return row["value"] if row else None

    async def set_kv(self, key: str, value: str) -> None:
        await self._conn.execute(
            "INSERT INTO kv (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        await self._conn.commit()

    async def delete_kv(self, key: str) -> bool:
        """Delete `key`; returns True when a row was removed."""
        cur = await self._conn.execute("DELETE FROM kv WHERE key = ?", (key,))
        await self._conn.commit()
        return cur.rowcount > 0

    # ---- auto-tuning (design 5.12) ----------------------------------------

    async def insert_tuning_change(self, change: TuningChange) -> None:
        await self._conn.execute(
            "INSERT INTO tuning_log (ts, rule, field, old, new, reason) VALUES (?, ?, ?, ?, ?, ?)",
            (change.ts.isoformat(), change.rule, change.field, change.old, change.new, change.reason),
        )
        await self._conn.commit()

    async def tuning_log(self, limit: int) -> list[TuningChange]:
        """The most recent `limit` tuning changes, newest first."""
        cur = await self._conn.execute("SELECT * FROM tuning_log ORDER BY id DESC LIMIT ?", (limit,))
        rows = await cur.fetchall()
        return [
            TuningChange(
                ts=datetime.fromisoformat(r["ts"]),
                rule=r["rule"],
                field=r["field"],
                old=r["old"],
                new=r["new"],
                reason=r["reason"],
            )
            for r in rows
        ]

    async def count_signals_since(self, ts: datetime) -> int:
        return await self._count_since("signals", ts)

    async def count_decisions_since(self, ts: datetime) -> int:
        return await self._count_since("decisions", ts)

    async def _count_since(self, table: str, ts: datetime) -> int:
        # `created_at` is stored as a UTC ISO string, which sorts chronologically.
        cur = await self._conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE created_at >= ?",
            (ts.astimezone(UTC).isoformat(),),
        )
        row = await cur.fetchone()
        return row[0] if row is not None else 0

    # ---- misc (beyond 5.10, used by later tasks' tests) ------------------

    async def count(self, table: str) -> int:
        if table not in _TABLES:
            raise ValueError(f"unknown table: {table}")
        cur = await self._conn.execute(f"SELECT COUNT(*) FROM {table}")
        row = await cur.fetchone()
        return row[0] if row is not None else 0
