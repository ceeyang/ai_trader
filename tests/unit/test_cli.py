import asyncio
from datetime import timedelta
from decimal import Decimal

from conftest import T0, make_signal
from typer.testing import CliRunner

from ai_trader.cli import app
from ai_trader.storage.db import Store


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
