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
