import asyncio
import logging

import httpx
from conftest import FakeRest, fake_ws_factory

from ai_trader.app import App, create_components
from ai_trader.execution.paper import PaperBroker
from ai_trader.settings import LLMConfig, Settings


def _http() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404)))


async def _components(tmp_path, exchange_info):
    s = Settings(_env_file=None, mode="paper", db_path=tmp_path / "a.db", llm=LLMConfig(enabled=False))
    return await create_components(s, rest=FakeRest(exchange_info), ws_factory=fake_ws_factory, http=_http())


async def test_create_components_paper_mode_wires_without_network(tmp_path, exchange_info):
    s = Settings(_env_file=None, mode="paper", db_path=tmp_path / "a.db", llm=LLMConfig(enabled=False))
    c = await create_components(s, rest=FakeRest(exchange_info), ws_factory=fake_ws_factory,
                          http=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404))))
    assert isinstance(c.broker, PaperBroker) and len(c.detectors) == 3 and c.risk is not None
    await c.http.aclose()


async def test_create_components_live_mode_requires_keys(tmp_path, exchange_info):
    import pytest

    s = Settings(_env_file=None, mode="live", db_path=tmp_path / "a.db", llm=LLMConfig(enabled=False))
    http = _http()
    with pytest.raises(SystemExit, match="BINANCE_API_KEY"):
        await create_components(s, rest=FakeRest(exchange_info), ws_factory=fake_ws_factory, http=http)
    await http.aclose()


async def test_app_start_stop_cleanly(tmp_path, exchange_info):
    c = await _components(tmp_path, exchange_info); app = App(c)
    task = asyncio.create_task(app.run()); await asyncio.sleep(0.2); await app.stop(); await asyncio.wait_for(task, 5)
    assert c.rest.closed and c.http.is_closed
    await app.stop()  # idempotent


async def test_app_stop_without_run_is_safe(tmp_path, exchange_info):
    c = await _components(tmp_path, exchange_info)
    app = App(c)
    await app.stop()
    await app.stop()


class CrashOnceComponent:
    def __init__(self) -> None:
        self.calls = 0
        self._stopped = asyncio.Event()

    async def run(self) -> None:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("boom")
        await self._stopped.wait()

    async def stop(self) -> None:
        self._stopped.set()


async def test_app_restarts_crashed_component(tmp_path, exchange_info, caplog):
    caplog.set_level(logging.INFO)
    c = await _components(tmp_path, exchange_info)
    fake = CrashOnceComponent()
    c.poller = fake
    app = App(c, backoff_s=(0.01,))
    task = asyncio.create_task(app.run())
    for _ in range(100):
        if fake.calls >= 2:
            break
        await asyncio.sleep(0.01)
    assert fake.calls >= 2 and not task.done()
    assert "restarting" in caplog.text
    await app.stop()
    await asyncio.wait_for(task, 5)


async def test_create_components_live_mode_syncs_time(tmp_path, exchange_info):
    from ai_trader.execution.binance import BinanceFuturesBroker

    class CountingRest(FakeRest):
        sync_calls = 0

        async def sync_time(self) -> int:
            self.sync_calls += 1
            return 0

    s = Settings(_env_file=None, mode="live", db_path=tmp_path / "a.db", llm=LLMConfig(enabled=False),
                 binance_api_key="k", binance_api_secret="s")
    rest = CountingRest(exchange_info)
    http = _http()
    c = await create_components(s, rest=rest, ws_factory=fake_ws_factory, http=http)
    assert isinstance(c.broker, BinanceFuturesBroker) and rest.sync_calls == 1
    await http.aclose()


async def test_create_components_closes_own_clients_on_failure(tmp_path, monkeypatch):
    import pytest

    import ai_trader.app as app_mod

    created: list[httpx.AsyncClient] = []
    real_client = httpx.AsyncClient

    def _client(*a, **kw):
        client = real_client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
        created.append(client)
        return client

    class BrokenRest:
        closed = False

        async def exchange_info(self):
            raise RuntimeError("exchange down")

        async def aclose(self) -> None:
            self.closed = True

    monkeypatch.setattr(app_mod.httpx, "AsyncClient", _client)
    s = Settings(_env_file=None, mode="paper", db_path=tmp_path / "a.db", llm=LLMConfig(enabled=False))
    rest = BrokenRest()
    with pytest.raises(RuntimeError, match="exchange down"):
        await create_components(s, rest=rest)
    assert created and created[0].is_closed
    assert rest.closed is False  # injected: the caller owns it


async def test_create_components_wires_autotuner_to_shared_configs(tmp_path, exchange_info):
    c = await _components(tmp_path, exchange_info)
    assert c.tuner.strategy_cfg is c.settings.strategy and c.tuner.detector_cfg is c.settings.detectors
    assert not any(v is c.settings.risk for v in vars(c.tuner).values())
    await c.http.aclose()


async def test_app_runs_autotuner_supervised(tmp_path, exchange_info):
    from ai_trader.strategy.autotune import AutoTuner

    c = await _components(tmp_path, exchange_info)
    c.tuner = AutoTuner(c.store, c.settings.strategy, c.settings.detectors, interval_s=0.05)
    app = App(c)
    task = asyncio.create_task(app.run())
    for _ in range(200):
        if c.store._db is not None and await c.store.tuning_log(1):
            break
        await asyncio.sleep(0.01)
    snapshot = await c.store.get_kv("tuning_effective")
    changes = await c.store.tuning_log(10)
    await app.stop()
    await asyncio.wait_for(task, 5)
    assert snapshot is not None
    # empty DB: the first tick's activity_floor relaxes the shared config the aggregator reads
    assert {ch.rule for ch in changes} == {"activity_floor"}
    assert c.settings.strategy.entry_threshold < 0.6


async def test_paper_broker_state_survives_app_restart(tmp_path, exchange_info):
    from decimal import Decimal

    from conftest import make_mark_price

    from ai_trader.models import OrderRequest, OrderType, Side

    c = await _components(tmp_path, exchange_info)
    assert c.broker._store is c.store
    await c.store.open()
    await c.broker.start()
    c.state.update_mark(make_mark_price(mark=Decimal(80000)))
    await c.broker.submit(OrderRequest(symbol="BTCUSDT", side=Side.BUY, type=OrderType.MARKET,
                                       quantity=Decimal("0.002"), client_order_id="ait-e"))
    balance = c.broker.wallet_balance
    await c.store.close()
    await c.http.aclose()

    c2 = await _components(tmp_path, exchange_info)
    await c2.store.open()
    await c2.broker.start()
    assert c2.broker.wallet_balance == balance
    assert c2.broker.positions_snapshot()["BTCUSDT"].quantity == Decimal("0.002")
    await c2.store.close()
    await c2.http.aclose()


class CountingKillSwitch:
    def __init__(self, real) -> None:
        self._real = real
        self.calls: list[str] = []

    @property
    def triggered(self) -> bool:
        return self._real.triggered

    @triggered.setter
    def triggered(self, value: bool) -> None:
        self._real.triggered = value

    async def trigger(self, reason: str) -> None:
        self.calls.append(reason)
        await self._real.trigger(reason)

    @property
    def last_errors(self) -> list[str]:
        return self._real.last_errors

    async def is_active(self) -> bool:
        return await self._real.is_active()


async def _wait_for(pred, n=300):
    for _ in range(n):
        if pred():
            return True
        await asyncio.sleep(0.01)
    return False


async def test_control_loop_triggers_kill_switch_once_and_flattens(tmp_path, exchange_info):
    from decimal import Decimal

    from conftest import make_mark_price

    from ai_trader.models import OrderRequest, OrderType, Side

    c = await _components(tmp_path, exchange_info)
    ks = CountingKillSwitch(c.kill_switch)
    c.kill_switch = ks
    app = App(c, control_interval_s=0.02)
    task = asyncio.create_task(app.run())
    assert await _wait_for(lambda: c.store._db is not None)
    c.state.update_mark(make_mark_price(mark=Decimal(80000)))
    c.state.update_mark(make_mark_price(symbol="ETHUSDT", mark=Decimal(3000)))
    await c.broker.submit(OrderRequest(symbol="BTCUSDT", side=Side.BUY, type=OrderType.MARKET,
                                       quantity=Decimal("0.002"), client_order_id="ait-k"))
    await c.store.set_kv("kill_switch", "1")
    assert await _wait_for(lambda: bool(ks.calls))
    await asyncio.sleep(0.1)  # several more control passes with the flag still set
    assert ks.calls == ["kill flag observed"]
    assert c.broker.positions_snapshot() == {}
    await app.stop()
    await asyncio.wait_for(task, 5)


async def test_stop_flag_stops_app_and_is_reset(tmp_path, exchange_info):
    c = await _components(tmp_path, exchange_info)
    app = App(c, control_interval_s=0.02)
    task = asyncio.create_task(app.run())
    assert await _wait_for(lambda: c.store._db is not None)
    await c.store.set_kv("stop_requested", "1")
    await asyncio.wait_for(task, 5)
    assert c.rest.closed
    from ai_trader.storage.db import Store

    st = Store(tmp_path / "a.db")
    await st.open()
    assert await st.get_kv("stop_requested") == "0"
    await st.close()


async def test_stale_stop_flag_is_cleared_at_start(tmp_path, exchange_info):
    from ai_trader.storage.db import Store

    st = Store(tmp_path / "a.db")
    await st.open()
    await st.set_kv("stop_requested", "1")
    await st.close()
    c = await _components(tmp_path, exchange_info)
    app = App(c, control_interval_s=0.02)
    task = asyncio.create_task(app.run())
    await asyncio.sleep(0.2)
    assert not task.done()
    await app.stop()
    await asyncio.wait_for(task, 5)


async def test_create_components_rejects_leverage_above_risk_cap(tmp_path, exchange_info):
    import pytest

    from ai_trader.settings import RiskLimits

    s = Settings(_env_file=None, mode="paper", db_path=tmp_path / "a.db", llm=LLMConfig(enabled=False),
                 leverage=5, risk=RiskLimits(max_leverage=3))
    http = _http()
    with pytest.raises(SystemExit, match="MAX_LEVERAGE"):
        await create_components(s, rest=FakeRest(exchange_info), ws_factory=fake_ws_factory, http=http)
    await http.aclose()



async def _paper_position_with_protection(c):
    """Open a BTCUSDT paper position with a resting SL/TP pair, then drop every mark so
    the state looks like a fresh boot with restored positions."""
    from decimal import Decimal

    from conftest import make_mark_price

    from ai_trader.data.market_state import MarketState
    from ai_trader.models import OrderRequest, OrderType, Side

    await c.store.open()
    await c.broker.start()
    c.state.update_mark(make_mark_price(mark=Decimal(80000)))
    await c.broker.submit(OrderRequest(symbol="BTCUSDT", side=Side.BUY, type=OrderType.MARKET,
                                       quantity=Decimal("0.002"), client_order_id="ait-e"))
    for cid, typ, px in (("ait-sl", OrderType.STOP_MARKET, "79000.0"),
                         ("ait-tp", OrderType.TAKE_PROFIT_MARKET, "82000.0")):
        await c.broker.submit(OrderRequest(symbol="BTCUSDT", side=Side.SELL, type=typ,
                                           stop_price=Decimal(px), close_position=True, client_order_id=cid))
    fresh = MarketState()  # no marks yet, as right after a restart
    c.state = fresh
    c.broker._state = fresh
    c.broker._event_marks.clear()
    return fresh


async def test_leftover_kill_flag_waits_for_fresh_marks_then_flattens(tmp_path, exchange_info):
    from decimal import Decimal

    from conftest import make_mark_price

    c = await _components(tmp_path, exchange_info)
    state = await _paper_position_with_protection(c)
    await c.store.set_kv("kill_switch", "1")
    ks = CountingKillSwitch(c.kill_switch)
    c.kill_switch = ks
    app = App(c)

    await app._check_control()  # boot: no marks -> nothing touched
    assert ks.calls == [] and not app._kill_handled
    assert set(c.broker._pending) == {"ait-sl", "ait-tp"}
    assert "BTCUSDT" in c.broker.positions_snapshot()

    state.update_mark(make_mark_price(mark=Decimal(80000)))
    await app._check_control()  # ETHUSDT still has no mark
    assert ks.calls == []

    state.update_mark(make_mark_price(symbol="ETHUSDT", mark=Decimal(3000)))
    await app._check_control()
    assert ks.calls == ["kill flag observed"] and app._kill_handled
    assert c.broker.positions_snapshot() == {} and c.broker._pending == {}
    await app._check_control()  # handled: no second sweep
    assert len(ks.calls) == 1
    await c.store.close()
    await c.http.aclose()


async def test_kill_sweep_with_failing_close_keeps_protection_and_retries(tmp_path, exchange_info):
    from decimal import Decimal

    from conftest import make_mark_price

    c = await _components(tmp_path, exchange_info)
    state = await _paper_position_with_protection(c)
    await c.store.set_kv("kill_switch", "1")
    ks = CountingKillSwitch(c.kill_switch)
    c.kill_switch = ks
    app = App(c)
    # Marks look fresh to the control loop, but the broker cannot price BTCUSDT yet.
    real_can_close = c.broker.can_close
    c.broker.can_close = lambda symbol: False
    state.update_mark(make_mark_price(mark=Decimal(80000)))
    state.update_mark(make_mark_price(symbol="ETHUSDT", mark=Decimal(3000)))

    await app._check_control()
    assert ks.calls == ["kill flag observed"] and not app._kill_handled
    assert set(c.broker._pending) == {"ait-sl", "ait-tp"}  # SL/TP still resting
    assert "BTCUSDT" in c.broker.positions_snapshot()
    assert any("not closable" in e for e in ks.last_errors)

    c.broker.can_close = real_can_close
    await app._check_control()  # retried on the next pass
    assert len(ks.calls) == 2 and app._kill_handled
    assert c.broker.positions_snapshot() == {} and c.broker._pending == {}
    await c.store.close()
    await c.http.aclose()
