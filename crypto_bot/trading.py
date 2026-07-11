"""High-level trade actions combining order placement, position lookup,
and stop-loss protection -- the entry points a future command interface
(Telegram or otherwise) will call, rather than wiring features 4/5/6
together ad hoc at each call site.
"""

from dataclasses import dataclass
from decimal import Decimal

from alpaca.data.historical.crypto import CryptoHistoricalDataClient
from alpaca.trading.client import TradingClient

from crypto_bot.exits import ProtectiveOrders, RiskTier, attach_protective_orders
from crypto_bot.orders import OrderResult, place_market_order
from crypto_bot.positions import PositionError, get_open_positions


class TradingError(Exception):
    """Raised when opening a protected position fails partway through."""


@dataclass(frozen=True)
class OpenedPosition:
    order: OrderResult
    protective_orders: ProtectiveOrders


def open_protected_position(
    client: TradingClient,
    data_client: CryptoHistoricalDataClient,
    symbol: str,
    notional: Decimal,
    tier: RiskTier,
) -> OpenedPosition:
    """Places a market buy order, then attaches a stop-loss sized from
    the position's *actual* quantity -- not the order's `filled_qty`.

    Confirmed live (2026-07-10): Alpaca deducts its crypto trading fee
    from the asset itself, so `filled_qty` overstates what you actually
    end up holding by roughly the fee percentage. Using it directly to
    size the stop-loss order causes an "insufficient balance" failure on
    an otherwise-normal, successful trade. Fetching the real position
    quantity via `get_open_positions` right before attaching avoids
    this.

    Buy-only: Alpaca crypto is spot-only (no short selling), so there's
    no meaningful "open a protected short" case to support here.
    """
    order = place_market_order(client, symbol, "buy", notional)
    if order.status != "FILLED":
        raise TradingError(
            f"Order for {symbol} did not fill (status={order.status}); no stop-loss attached"
        )

    no_slash_symbol = symbol.replace("/", "")
    try:
        positions = get_open_positions(client)
    except PositionError as exc:
        raise TradingError(f"Order filled but failed to fetch position for {symbol}") from exc

    position = next((p for p in positions if p.symbol == no_slash_symbol), None)
    if position is None:
        raise TradingError(f"Order filled but no open position found for {symbol}")

    protective_orders = attach_protective_orders(
        client, data_client, symbol, position.qty, order.filled_avg_price, tier
    )
    return OpenedPosition(order=order, protective_orders=protective_orders)
