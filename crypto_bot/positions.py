"""Reads currently open crypto positions from Alpaca.

Read-only -- fetches a snapshot, doesn't modify anything. Alpaca nets
positions per symbol (one position per symbol), unlike OANDA's
per-trade model.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from alpaca.common.exceptions import APIError
from alpaca.trading.client import TradingClient


class PositionError(Exception):
    """Raised when Alpaca rejects or fails an open-positions request."""


@dataclass(frozen=True)
class OpenPosition:
    symbol: str
    qty: Decimal
    side: Literal["long", "short"]
    avg_entry_price: Decimal
    unrealized_pl: Decimal


def get_open_positions(client: TradingClient) -> list[OpenPosition]:
    try:
        positions = client.get_all_positions()
    except APIError as exc:
        raise PositionError("Failed to fetch open positions") from exc

    return [
        OpenPosition(
            symbol=p.symbol,
            qty=Decimal(str(p.qty)),
            side="long" if str(p.side).split(".")[-1].lower() == "long" else "short",
            avg_entry_price=Decimal(str(p.avg_entry_price)),
            unrealized_pl=Decimal(str(p.unrealized_pl)),
        )
        for p in positions
    ]


if __name__ == "__main__":
    import logging

    from crypto_bot.alpaca_client import get_client
    from crypto_bot.config import load_settings

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    settings = load_settings()
    client = get_client(settings)
    positions = get_open_positions(client)

    if not positions:
        print("No open positions.")
    else:
        for p in positions:
            print(
                f"{p.symbol}  qty={p.qty}  side={p.side}  "
                f"entry={p.avg_entry_price}  unrealized_pl={p.unrealized_pl}"
            )
