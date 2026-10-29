"""WebSocket client for Binance USDT-M futures market/user data streams (design 5.4)."""

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from typing import Any, Protocol
from urllib.parse import urlsplit

import websockets

log = logging.getLogger(__name__)

_DEFAULT_BACKOFF_S: Sequence[float] = (1, 2, 5, 10, 30)


def market_stream_url(base_ws: str, streams: Sequence[str]) -> str:
    return f"{base_ws}/stream?streams=" + "/".join(streams)


def user_stream_url(base_ws: str, listen_key: str) -> str:
    return f"{base_ws}/ws/{listen_key}"


def redact_url(url: str) -> str:
    """A loggable form of `url`: a user-data stream (`/ws/<listenKey>`) is reduced to
    scheme + host + `/ws/<listenKey>`, since the listen key grants access to account data."""
    parts = urlsplit(url)
    if "/ws/" in parts.path:
        return f"{parts.scheme}://{parts.netloc}/ws/<listenKey>"
    return url


class _Conn(Protocol):
    """The part of a websockets client connection this module uses."""

    def __aiter__(self) -> AsyncIterator[str | bytes]: ...

    async def close(self) -> None: ...


class BinanceFuturesWS:
    """Reconnecting WS client. Combined-stream envelopes (`{"stream", "data"}`) are
    unwrapped before dispatch; single-stream messages pass through unchanged."""

    def __init__(
        self,
        url: str,
        handler: Callable[[dict], Awaitable[None]],
        *,
        backoff_s: Sequence[float] = _DEFAULT_BACKOFF_S,
        connect: Callable[..., Any] = websockets.connect,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._url = url
        self._handler = handler
        self._backoff_s = backoff_s
        self._connect = connect
        self._clock = clock
        self._stopped = False
        self._stop_event = asyncio.Event()
        self._conn: _Conn | None = None
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
                    if self._stopped:
                        # stop() landed during the connect handshake, while self._conn
                        # was still None for it to close; closing `conn` here (via the
                        # `async with` exit below) is what makes that race safe.
                        break
                    async for raw in conn:
                        try:
                            msg = json.loads(raw)
                        except Exception:
                            log.exception("Binance WS received a malformed frame, skipping")
                            continue
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
            log.warning(
                "Binance WS connection to %s closed, reconnecting: %s",
                redact_url(self._url),
                self._redact(f"{type(error).__name__}: {error}" if error is not None else "closed"),
            )
            sleep_s = self._backoff_s[min(backoff_i, len(self._backoff_s) - 1)]
            self.reconnects += 1
            backoff_i += 1
            # Interruptible sleep: stop() sets _stop_event so this returns immediately
            # instead of blocking for the full backoff delay (up to 30s by default).
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop_event.wait(), timeout=sleep_s)

    def _redact(self, text: str) -> str:
        """Strip a user-stream listen key from free text (e.g. an exception echoing the URL)."""
        path = urlsplit(self._url).path
        if "/ws/" in path:
            key = path.rsplit("/ws/", 1)[1]
            if key:
                text = text.replace(key, "<listenKey>")
        return text

    async def stop(self) -> None:
        self._stopped = True
        self._stop_event.set()
        if self._conn is not None:
            await self._conn.close()
