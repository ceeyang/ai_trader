"""WebSocket client for Binance USDT-M futures market/user data streams (design 5.4)."""

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable, Sequence

import websockets

log = logging.getLogger(__name__)

_DEFAULT_BACKOFF_S: Sequence[float] = (1, 2, 5, 10, 30)


def market_stream_url(base_ws: str, streams: Sequence[str]) -> str:
    return f"{base_ws}/stream?streams=" + "/".join(streams)


def user_stream_url(base_ws: str, listen_key: str) -> str:
    return f"{base_ws}/ws/{listen_key}"


class BinanceFuturesWS:
    """Reconnecting WS client. Combined-stream envelopes (`{"stream", "data"}`) are
    unwrapped before dispatch; single-stream messages pass through unchanged."""

    def __init__(
        self,
        url: str,
        handler: Callable[[dict], Awaitable[None]],
        *,
        backoff_s: Sequence[float] = _DEFAULT_BACKOFF_S,
        connect: Callable[..., object] = websockets.connect,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._url = url
        self._handler = handler
        self._backoff_s = backoff_s
        self._connect = connect
        self._clock = clock
        self._stopped = False
        self._conn: object | None = None
        self.last_message_at: float | None = None
        self.reconnects = 0

    async def run(self) -> None:
        backoff_i = 0
        while not self._stopped:
            error: BaseException | None = None
            try:
                async with self._connect(self._url) as conn:
                    self._conn = conn
                    backoff_i = 0  # a successful connection resets the backoff index
                    async for raw in conn:
                        msg = json.loads(raw)
                        self.last_message_at = self._clock()
                        try:
                            await self._handler(msg.get("data", msg))
                        except Exception:
                            log.exception("Binance WS handler raised")
            except Exception as exc:  # noqa: BLE001 - any connection close/error is retried
                error = exc
            finally:
                self._conn = None

            if self._stopped:
                break
            log.warning("Binance WS connection to %s closed, reconnecting: %s", self._url, error)
            sleep_s = self._backoff_s[min(backoff_i, len(self._backoff_s) - 1)]
            self.reconnects += 1
            backoff_i += 1
            await asyncio.sleep(sleep_s)

    async def stop(self) -> None:
        self._stopped = True
        if self._conn is not None:
            await self._conn.close()
