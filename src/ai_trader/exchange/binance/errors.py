"""Binance adapter exceptions (design 5.4)."""


class BinanceError(Exception):
    """Base class for Binance adapter errors."""


class BinanceAPIError(BinanceError):
    """Non-2xx response from Binance, carrying its `{"code", "msg"}` payload."""

    def __init__(self, status: int, code: int, msg: str) -> None:
        super().__init__(f"HTTP {status} code={code} msg={msg}")
        self.status = status
        self.code = code
        self.msg = msg


class BinanceRateLimitError(BinanceAPIError):
    """HTTP 429 / 418: request weight exceeded or IP banned."""

    def __init__(self, status: int, code: int, msg: str, retry_after_s: float | None = None) -> None:
        super().__init__(status, code, msg)
        self.retry_after_s = retry_after_s


class BinanceConnectionError(BinanceError):
    """Transport-level failure (connect / read / timeout) talking to Binance."""


class FilterViolation(ValueError):
    """Order quantity / price does not satisfy the symbol's exchange filters."""


class UnknownSymbol(KeyError):
    """Symbol is not a trading perpetual in the loaded exchange info."""
