import asyncio
from datetime import timedelta
from decimal import Decimal

import pytest
from conftest import T0, fx, make_signal
from typer.testing import CliRunner

from ai_trader.cli import app
from ai_trader.storage.db import Store


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    """`Settings()` reads `.env` from the working directory: never the developer's real one."""
    monkeypatch.chdir(tmp_path)


async def _kv(path, key):
    st = Store(path)
    await st.open()
    try:
        return await st.get_kv(key)
    finally:
        await st.close()


def test_cli_run_live_mainnet_requires_confirm(monkeypatch):
    monkeypatch.setenv("BINANCE_TESTNET", "false")
    r = CliRunner().invoke(app, ["run", "--mode", "live"])
    assert r.exit_code == 2 and "--confirm-mainnet" in r.output


async def _seed(path):
    st = Store(path)
    await st.open()
    await st.insert_signal(make_signal("s1", detector="funding_extreme", created_at=T0))
    await st.insert_mark_sample("BTCUSDT", T0 + timedelta(seconds=600), Decimal(80800))
    await st.insert_forward_return("s1", 600, 0.01)
    await st.close()


def test_cli_signals_prints_table(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "x.db"))
    asyncio.run(_seed(tmp_path / "x.db"))     # 写入 1 条 funding_extreme 信号 + forward_return(600)
    r = CliRunner().invoke(app, ["signals"]); assert r.exit_code == 0 and "funding_extreme" in r.output and "600" in r.output


def test_cli_signals_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "y.db"))
    r = CliRunner().invoke(app, ["signals"])
    assert r.exit_code == 0 and "no data yet" in r.output


def test_cli_kill_paper_sets_flag_and_status_shows_it(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "z.db"))
    monkeypatch.setenv("MODE", "paper")
    r = CliRunner().invoke(app, ["kill"])
    assert r.exit_code == 0

    async def _flag():
        st = Store(tmp_path / "z.db")
        await st.open()
        try:
            return await st.get_kv("kill_switch")
        finally:
            await st.close()

    assert asyncio.run(_flag()) == "1"
    asyncio.run(_seed(tmp_path / "z.db"))
    r = CliRunner().invoke(app, ["status"])
    assert r.exit_code == 0 and "ACTIVE" in r.output and "funding_extreme" in r.output


def test_cli_kill_live_sets_flag_even_when_rest_fails(tmp_path, monkeypatch):
    import httpx
    import respx

    monkeypatch.setenv("DB_PATH", str(tmp_path / "k.db"))
    monkeypatch.setenv("MODE", "live")
    monkeypatch.setenv("BINANCE_API_KEY", "k")
    monkeypatch.setenv("BINANCE_API_SECRET", "s")
    with respx.mock(assert_all_called=False) as mock:
        mock.route().mock(side_effect=httpx.ConnectError("down"))
        r = CliRunner().invoke(app, ["kill"])
    assert r.exit_code == 1 and "flatten NOT run" in r.output and "flattened" not in r.output

    async def _flag():
        st = Store(tmp_path / "k.db")
        await st.open()
        try:
            return await st.get_kv("kill_switch")
        finally:
            await st.close()

    assert asyncio.run(_flag()) == "1"


async def _seed_tuning(path):
    from ai_trader.settings import DetectorConfig, StrategyConfig
    from ai_trader.strategy.autotune import AutoTuner

    st = Store(path)
    await st.open()
    await AutoTuner(st, StrategyConfig(), DetectorConfig(), clock=lambda: T0.timestamp()).tick()
    await st.close()


def test_cli_tuning_prints_log(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    asyncio.run(_seed_tuning(tmp_path / "t.db"))
    r = CliRunner().invoke(app, ["tuning"])
    assert r.exit_code == 0
    assert "activity_floor" in r.output and "strategy.entry_threshold" in r.output and "35000" in r.output


def test_cli_tuning_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "e.db"))
    r = CliRunner().invoke(app, ["tuning"])
    assert r.exit_code == 0 and "no tuning changes yet" in r.output


def test_cli_status_prints_effective_parameters(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "s.db"))
    monkeypatch.setenv("MODE", "paper")
    r = CliRunner().invoke(app, ["status"])
    assert r.exit_code == 0 and "configured defaults" in r.output and "entry_threshold=0.6" in r.output
    asyncio.run(_seed_tuning(tmp_path / "s.db"))
    r = CliRunner().invoke(app, ["status"])
    assert r.exit_code == 0 and "effective (from running process)" in r.output
    assert "entry_threshold=0.55" in r.output and "liquidation_notional_threshold_usdt=35000" in r.output
    assert "cooldown_s=900" in r.output and "news_sentiment" in r.output


def test_cli_status_paper_prints_persisted_positions(tmp_path, monkeypatch):
    import json

    monkeypatch.setenv("DB_PATH", str(tmp_path / "p.db"))
    monkeypatch.setenv("MODE", "paper")

    async def _seed_paper():
        st = Store(tmp_path / "p.db")
        await st.open()
        await st.set_kv("paper_state", json.dumps({
            "version": 1, "wallet_balance": "9990.5", "realized_pnl": "-9.5", "next_order_id": 4,
            "positions": {"BTCUSDT": {"qty": "-0.002", "entry_price": "80000"}},
            "pending": [{"order_id": 2, "request": {
                "symbol": "BTCUSDT", "side": "BUY", "type": "STOP_MARKET", "quantity": None, "price": None,
                "stop_price": "80800", "reduce_only": False, "close_position": True,
                "client_order_id": "ait-sl", "time_in_force": None}}],
        }))
        await st.close()

    asyncio.run(_seed_paper())
    r = CliRunner().invoke(app, ["status"])
    assert r.exit_code == 0
    assert "wallet=9990.5" in r.output and "BTCUSDT" in r.output and "SHORT" in r.output
    assert "STOP_MARKET" in r.output and "ait-sl" in r.output


def test_cli_status_survives_unreadable_kv(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "u.db"))
    monkeypatch.setenv("MODE", "paper")

    async def _seed_bad():
        st = Store(tmp_path / "u.db")
        await st.open()
        await st.set_kv("tuning_effective", '{"strategy": {')
        await st.set_kv("paper_state", '{"wallet_balance": "1"}')
        await st.close()

    asyncio.run(_seed_bad())
    r = CliRunner().invoke(app, ["status"])
    assert r.exit_code == 0
    assert "unreadable kv `tuning_effective`" in r.output and "unreadable kv `paper_state`" in r.output
    assert "last signals" in r.output


def test_cli_stop_sets_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "stop.db"))
    r = CliRunner().invoke(app, ["stop"])
    assert r.exit_code == 0 and "15 s" in r.output
    assert asyncio.run(_kv(tmp_path / "stop.db", "stop_requested")) == "1"


def test_cli_kill_reset_clears_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "r.db"))
    monkeypatch.setenv("MODE", "paper")
    assert CliRunner().invoke(app, ["kill"]).exit_code == 0
    assert asyncio.run(_kv(tmp_path / "r.db", "kill_switch")) == "1"
    r = CliRunner().invoke(app, ["kill", "--reset"])
    assert r.exit_code == 0 and "inactive" in r.output
    assert asyncio.run(_kv(tmp_path / "r.db", "kill_switch")) == "0"


def test_cli_kill_live_reports_flatten_failures(tmp_path, monkeypatch):
    import httpx
    import respx

    base = "https://testnet.binancefuture.com"
    monkeypatch.setenv("DB_PATH", str(tmp_path / "f.db"))
    monkeypatch.setenv("MODE", "live")
    monkeypatch.setenv("BINANCE_API_KEY", "k")
    monkeypatch.setenv("BINANCE_API_SECRET", "s")
    err = httpx.Response(400, json={"code": -1000, "msg": "nope"})
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{base}/fapi/v1/time").respond(json={"serverTime": 1793217600000})
        mock.get(f"{base}/fapi/v1/exchangeInfo").respond(json=fx("exchange_info.json"))
        mock.get(url__startswith=f"{base}/fapi/v2/positionRisk").respond(json=fx("position_risk_v2.json"))
        mock.get(url__startswith=f"{base}/fapi/v1/openOrders").respond(json=[])
        mock.delete(url__startswith=f"{base}/fapi/v1/allOpenOrders").mock(return_value=err)
        mock.post(f"{base}/fapi/v1/order").mock(return_value=err)
        r = CliRunner().invoke(app, ["kill"])
    assert r.exit_code == 1, r.output
    assert "had failures" in r.output and "BTCUSDT cancel_all" in r.output and "BTCUSDT close_position" in r.output
    assert asyncio.run(_kv(tmp_path / "f.db", "kill_switch")) == "1"
