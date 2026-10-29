import asyncio, json, time  # noqa: I001
import websockets
from ai_trader.exchange.binance.ws import BinanceFuturesWS, market_stream_url, user_stream_url


def test_urls():
    assert market_stream_url("wss://x", ["a@b", "c@d"]) == "wss://x/stream?streams=a@b/c@d"
    assert user_stream_url("wss://x", "LK") == "wss://x/ws/LK"


async def test_receives_unwraps_and_reconnects():
    conns = 0
    async def server(ws):
        nonlocal conns; conns += 1
        await ws.send(json.dumps({"stream": "s", "data": {"e": "ping", "n": conns}}))
        await ws.close()
    async with websockets.serve(server, "127.0.0.1", 0) as srv:
        port = srv.sockets[0].getsockname()[1]
        got = []
        async def h(m): got.append(m)
        ws = BinanceFuturesWS(f"ws://127.0.0.1:{port}", h, backoff_s=(0.05,))
        task = asyncio.create_task(ws.run())
        for _ in range(100):
            if len(got) >= 2: break
            await asyncio.sleep(0.05)
        await ws.stop(); await task
    assert [m["n"] for m in got[:2]] == [1, 2] and ws.reconnects >= 1 and ws.last_message_at is not None


async def test_stop_during_backoff_sleep_returns_promptly():
    """stop() must interrupt a realistic (multi-second) backoff wait, not just the
    short one used by test_receives_unwraps_and_reconnects."""

    async def server(ws):
        await ws.close()  # disconnect immediately, forcing the client into backoff

    async with websockets.serve(server, "127.0.0.1", 0) as srv:
        port = srv.sockets[0].getsockname()[1]

        async def h(m):
            pass

        ws = BinanceFuturesWS(f"ws://127.0.0.1:{port}", h, backoff_s=(5.0,))
        task = asyncio.create_task(ws.run())
        for _ in range(100):
            if ws.reconnects >= 1:
                break
            await asyncio.sleep(0.02)
        assert ws.reconnects >= 1  # confirms run() is now inside the 5s backoff sleep

        start = time.monotonic()
        await ws.stop()
        await asyncio.wait_for(task, timeout=0.5)
        assert time.monotonic() - start < 0.5


async def test_user_stream_log_lines_do_not_contain_the_listen_key(caplog):
    import logging

    from ai_trader.exchange.binance.ws import redact_url

    assert redact_url("wss://h.example/ws/SECRETKEY") == "wss://h.example/ws/<listenKey>"
    assert redact_url("wss://h/stream?streams=a@b") == "wss://h/stream?streams=a@b"

    async def server(ws):
        await ws.close()

    async with websockets.serve(server, "127.0.0.1", 0) as srv:
        port = srv.sockets[0].getsockname()[1]

        async def h(m):
            pass

        ws = BinanceFuturesWS(f"ws://127.0.0.1:{port}/ws/SECRETKEY", h, backoff_s=(0.02,))
        with caplog.at_level(logging.DEBUG):
            task = asyncio.create_task(ws.run())
            for _ in range(100):
                if ws.reconnects >= 1:
                    break
                await asyncio.sleep(0.02)
            await ws.stop()
            await task
    ours = " | ".join(r.getMessage() for r in caplog.records if r.name.startswith("ai_trader"))
    assert ws.reconnects >= 1 and "<listenKey>" in ours
    assert "SECRETKEY" not in ours
