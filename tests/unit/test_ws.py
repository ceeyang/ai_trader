import asyncio, json  # noqa: I001
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
