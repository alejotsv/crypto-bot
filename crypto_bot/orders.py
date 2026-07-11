"""Places market orders via Alpaca's TradingClient.

Alpaca's order submission is asynchronous -- a submitted order comes
back as PENDING_NEW, not filled, unlike OANDA's synchronous single-
response fill. This module polls for a terminal status rather than
trusting the initial response.

No stop-loss/take-profit attached here -- callers attach that separately
via crypto_bot.exits (see ADR 0004: Alpaca doesn't support bracket/OCO
orders for crypto at all).
"""

import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from alpaca.common.exceptions import APIError
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest

MIN_NOTIONAL = Decimal("10")
POLL_INTERVAL_SECONDS = 1
MAX_POLL_ATTEMPTS = 10
TERMINAL_STATUSES = {"filled", "rejected", "canceled", "expired"}


class OrderError(Exception):
    """Raised when Alpaca rejects or fails an order request."""


@dataclass(frozen=True)
class OrderResult:
    status: Literal["FILLED", "REJECTED", "CANCELED"]
    order_id: str
    symbol: str
    side: Literal["buy", "sell"]
    filled_qty: Decimal | None
    filled_avg_price: Decimal | None


def poll_until_terminal(client: TradingClient, order_id: str, symbol: str):
    """Polls `get_order_by_id` until the order reaches a terminal status
    (Alpaca's order submission is asynchronous -- see module docstring).
    Returns the final Order object. Shared by `place_market_order` and
    any other action that submits an order and needs its settled result
    (e.g. `crypto_bot.exits.close_position`).
    """
    order = None
    for _ in range(MAX_POLL_ATTEMPTS):
        try:
            order = client.get_order_by_id(order_id)
        except APIError as exc:
            raise OrderError(f"Failed to check order status for {symbol}") from exc
        if str(order.status).split(".")[-1].lower() in TERMINAL_STATUSES:
            return order
        time.sleep(POLL_INTERVAL_SECONDS)
    raise OrderError(f"Order for {symbol} did not reach a terminal status in time")


def place_market_order(
    client: TradingClient,
    symbol: str,
    side: Literal["buy", "sell"],
    notional: Decimal,
) -> OrderResult:
    if notional < MIN_NOTIONAL:
        raise ValueError(f"notional must be >= {MIN_NOTIONAL}, got {notional}")
    if side not in ("buy", "sell"):
        raise ValueError(f"side must be 'buy' or 'sell', got {side!r}")

    order_data = MarketOrderRequest(
        symbol=symbol,
        notional=notional,
        side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
        time_in_force=TimeInForce.GTC,
    )
    try:
        order = client.submit_order(order_data)
    except APIError as exc:
        raise OrderError(f"Failed to place {side} order for {symbol}") from exc

    order = poll_until_terminal(client, order.id, symbol)

    status_name = str(order.status).split(".")[-1].upper()
    return OrderResult(
        status=status_name if status_name in ("FILLED", "REJECTED", "CANCELED") else "REJECTED",
        order_id=str(order.id),
        symbol=symbol,
        side=side,
        filled_qty=Decimal(str(order.filled_qty)) if order.filled_qty else None,
        filled_avg_price=Decimal(str(order.filled_avg_price)) if order.filled_avg_price else None,
    )


if __name__ == "__main__":
    import logging

    from crypto_bot.alpaca_client import get_client
    from crypto_bot.config import load_settings

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    settings = load_settings()
    client = get_client(settings)

    print(
        "Placing a REAL $10 market BUY order for BTC/USD on your "
        f"{'paper' if settings.alpaca_paper else 'LIVE'} account..."
    )
    result = place_market_order(client, "BTC/USD", "buy", Decimal("10"))
    print(result)
