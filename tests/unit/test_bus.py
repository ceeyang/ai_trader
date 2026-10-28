import asyncio  # noqa: I001
from ai_trader.bus import EventBus

class A: ...
class B(A): ...

async def _append(lst, e): lst.append(e)

async def test_delivers_by_isinstance():
    bus = EventBus(); got = []
    bus.subscribe(A, lambda e: _append(got, e))
    await bus.start(); bus.publish(B()); await bus.drain(); await bus.stop()
    assert len(got) == 1 and isinstance(got[0], B)

async def test_slow_handler_does_not_block_fast_one():
    bus = EventBus(); fast = []
    async def slow(e): await asyncio.sleep(0.5)
    bus.subscribe(A, slow); bus.subscribe(A, lambda e: _append(fast, e))
    await bus.start(); bus.publish(A()); await asyncio.sleep(0.05)
    assert len(fast) == 1
    await bus.stop()

async def test_handler_exception_is_isolated():
    bus = EventBus(); ok = []
    async def bad(e): raise RuntimeError("boom")
    bus.subscribe(A, bad); bus.subscribe(A, lambda e: _append(ok, e))
    await bus.start(); bus.publish(A()); await bus.drain(); await bus.stop()
    assert len(ok) == 1

async def test_overflow_drops_oldest_and_counts():
    bus = EventBus()
    async def never(e): await asyncio.sleep(10)
    bus.subscribe(A, never, maxsize=2)
    for _ in range(5): bus.publish(A())
    assert sum(bus.dropped.values()) == 3

async def test_late_subscription_after_start_gets_a_worker():
    bus = EventBus(); got = []
    await bus.start()
    bus.subscribe(A, lambda e: _append(got, e))  # subscribed after start()
    bus.publish(A())
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    await bus.drain()
    elapsed = loop.time() - t0
    await bus.stop()
    assert len(got) == 1
    assert elapsed < 0.5  # must not fall back to drain()'s 2.0s timeout
