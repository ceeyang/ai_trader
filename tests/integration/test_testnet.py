"""Testnet integration tests (design §6, Task 14).

`test_account_and_positions` / `test_place_far_limit_then_cancel` need a real testnet
API key/secret and are skipped without `BINANCE_API_KEY` / `BINANCE_API_SECRET`.
`test_public_ping_and_mark` only needs outbound network access (no keys) and is
skipped unless `AIT_NETWORK_TESTS=1`.
"""

import os
from decimal import Decimal

import pytest

from ai_trader.exchange.binance.rest import BinanceFuturesRest
from ai_trader.models import OrderRequest, OrderStatus, OrderType, Side, new_client_order_id
from ai_trader.settings import TESTNET_REST

pytestmark = pytest.mark.integration

KEY = os.getenv("BINANCE_API_KEY")
SEC = os.getenv("BINANCE_API_SECRET")
skip_no_key = pytest.mark.skipif(not (KEY and SEC), reason="需要测试网 BINANCE_API_KEY/BINANCE_API_SECRET")


@skip_no_key
async def test_account_and_positions():
    rest = BinanceFuturesRest(TESTNET_REST, KEY, SEC)
    try:
        await rest.sync_time()
        account = await rest.account()
        assert account.total_wallet_balance >= 0
    finally:
        await rest.aclose()


@skip_no_key
async def test_place_far_limit_then_cancel():
    rest = BinanceFuturesRest(TESTNET_REST, KEY, SEC)
    try:
        await rest.sync_time()
        filters = (await rest.exchange_info()).filters_for("BTCUSDT")
        mark_price = (await rest.premium_index("BTCUSDT")).mark_price
        price = filters.round_price(mark_price * Decimal("0.5"))
        qty = filters.qty_for_notional(Decimal("120"), price)  # noqa: FURB157
        client_order_id = new_client_order_id()

        placed = await rest.place_order(
            OrderRequest(
                symbol="BTCUSDT",
                side=Side.BUY,
                type=OrderType.LIMIT,
                quantity=qty,
                price=price,
                client_order_id=client_order_id,
                time_in_force="GTC",
            )
        )
        try:
            assert placed.status == OrderStatus.NEW
        finally:
            # Always attempt the cancel, even if the NEW assertion failed: never leave
            # a resting order on the testnet account.
            cancelled = await rest.cancel_order("BTCUSDT", client_order_id=client_order_id)
        assert cancelled.status == OrderStatus.CANCELED
    finally:
        await rest.aclose()


@pytest.mark.network
@pytest.mark.skipif(os.getenv("AIT_NETWORK_TESTS") != "1", reason="AIT_NETWORK_TESTS=1 才跑")
async def test_public_ping_and_mark():
    rest = BinanceFuturesRest(TESTNET_REST)
    try:
        await rest.ping()
        mark_price = (await rest.premium_index("BTCUSDT")).mark_price
        assert mark_price > 0
    finally:
        await rest.aclose()
