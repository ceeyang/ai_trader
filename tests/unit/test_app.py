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
