"""Stop-loss/take-profit for crypto positions.

Alpaca doesn't support bracket/OCO orders for crypto (see ADR 0004:
Market, Limit, and Stop Limit only). The original design placed both a
take-profit Limit order and a stop-loss Stop Limit order simultaneously
-- confirmed live (2026-07-10) this doesn't work: Alpaca locks the
*entire* position quantity against the first sell order submitted
(`qty_available` drops to 0 immediately), leaving no balance for a
second full-quantity sell order on the same position. Two live sell
orders for one position isn't possible here.

Actual design: only the **stop-loss** (a Stop Limit order) stays live
on Alpaca, continuously enforced by its own matching engine -- this is
the safety-critical leg, so it gets instant, exchange-side enforcement.
The **take-profit** target is tracked in this project's own persisted
state and checked by the reconciliation cron (feature 7): once price
reaches it, the stop-loss order is canceled and a market sell is
submitted to realize the gain. This means take-profit realization is
bound to the cron cadence (up to ~2 minutes late), not instant -- an
acceptable tradeoff since it only affects the upside, not the safety
property the stop-loss provides.

The same reconciliation check also backstops the stop-loss itself: if
price has crossed the stop-loss trigger but the Stop Limit order is
still unfilled (the real failure mode of a Stop Limit order in a fast
move -- price can gap through both the stop and limit price faster than
the order can fill), it cancels the stuck order and submits a market
sell instead, guaranteeing an eventual exit.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

from alpaca.common.exceptions import APIError
from alpaca.data.historical.crypto import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest, CryptoLatestQuoteRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest, StopLimitOrderRequest

from crypto_bot.exit_state import load_state, record_protective_orders, remove_protective_orders
from crypto_bot.orders import poll_until_terminal

DEFAULT_ATR_PERIOD = 14

RiskTier = Literal["conservative", "moderate", "aggressive"]

# (stop_multiplier, target_multiplier, buffer_multiplier) per tier --
# buffer_multiplier is fixed at stop_multiplier / 6 for each row.
RISK_TIER_ATR_MULTIPLIERS: dict[str, tuple[Decimal, Decimal, Decimal]] = {
    "conservative": (Decimal("1.5"), Decimal("2.5"), Decimal("0.25")),
    "moderate": (Decimal("3"), Decimal("6"), Decimal("0.5")),
    "aggressive": (Decimal("6"), Decimal("15"), Decimal("1")),
}


class ExitError(Exception):
    """Raised when Alpaca rejects or fails an exit-related request."""


@dataclass(frozen=True)
class ProtectiveOrders:
    stop_loss_order_id: str
    target_price: Decimal
    stop_price: Decimal
    limit_price: Decimal


@dataclass(frozen=True)
class CloseResult:
    order_id: str
    symbol: str
    status: Literal["FILLED", "REJECTED", "CANCELED"]
    filled_qty: Decimal | None
    filled_avg_price: Decimal | None


@dataclass(frozen=True)
class ReconcileAction:
    symbol: str
    action: Literal["STOP_LOSS_FILLED", "TAKE_PROFIT_REALIZED", "FORCED_MARKET_SELL"]
    detail: str


def get_atr(
    data_client: CryptoHistoricalDataClient, symbol: str, period: int = DEFAULT_ATR_PERIOD
) -> Decimal:
    request = CryptoBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Hour,
        start=datetime.now(timezone.utc) - timedelta(hours=period + 1),
    )
    try:
        bars = data_client.get_crypto_bars(request)[symbol]
    except APIError as exc:
        raise ExitError(f"Failed to fetch bars for {symbol}") from exc

    true_ranges = []
    for i in range(1, len(bars)):
        high = Decimal(str(bars[i].high))
        low = Decimal(str(bars[i].low))
        prev_close = Decimal(str(bars[i - 1].close))
        true_ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))

    return sum(true_ranges) / len(true_ranges)


def get_price_increment(client: TradingClient, symbol: str) -> Decimal:
    """Alpaca rejects prices with more precision than an asset allows
    (confirmed live: BTC/USD's `price_increment` is 1e-9, and ATR-derived
    prices routinely have more decimal places than that from plain
    Decimal division) -- fetch the real increment and quantize to it
    before submitting, rather than guessing a fixed precision.
    """
    try:
        asset = client.get_asset(symbol)
    except APIError as exc:
        raise ExitError(f"Failed to fetch price increment for {symbol}") from exc
    return Decimal(str(asset.price_increment))


def attach_protective_orders(
    client: TradingClient,
    data_client: CryptoHistoricalDataClient,
    symbol: str,
    qty: Decimal,
    entry_price: Decimal,
    tier: RiskTier,
) -> ProtectiveOrders:
    """Attaches only the stop-loss order (the safety-critical leg) to
    Alpaca. The take-profit target is computed and persisted but not
    submitted as a live order -- see module docstring for why.
    """
    stop_multiplier, target_multiplier, buffer_multiplier = RISK_TIER_ATR_MULTIPLIERS[tier]
    atr = get_atr(data_client, symbol)
    quantum = get_price_increment(client, symbol)
    target_price = (entry_price + (atr * target_multiplier)).quantize(quantum)
    limit_price = (entry_price - (atr * stop_multiplier)).quantize(quantum)
    stop_price = (limit_price + (atr * buffer_multiplier)).quantize(quantum)

    if stop_price <= limit_price:
        raise ValueError(
            f"stop_price ({stop_price}) must be above limit_price ({limit_price})"
        )

    try:
        stop_loss = client.submit_order(StopLimitOrderRequest(
            symbol=symbol, qty=qty, side=OrderSide.SELL,
            time_in_force=TimeInForce.GTC,
            stop_price=stop_price, limit_price=limit_price,
        ))
    except APIError as exc:
        raise ExitError(f"Failed to attach stop-loss order for {symbol}") from exc

    record_protective_orders(symbol, str(stop_loss.id), str(target_price), tier)

    return ProtectiveOrders(
        stop_loss_order_id=str(stop_loss.id),
        target_price=target_price,
        stop_price=stop_price,
        limit_price=limit_price,
    )


def check_and_reconcile_exits(
    client: TradingClient, data_client: CryptoHistoricalDataClient
) -> list[ReconcileAction]:
    """Runs on the project's cron cycle (feature 7). For each tracked
    position: realizes the take-profit target once price reaches it
    (canceling the stop-loss and submitting a market sell), and
    force-market-sells if the stop-loss order is stuck unfilled despite
    price having crossed its trigger.
    """
    actions: list[ReconcileAction] = []
    state = load_state()

    for symbol, tracked in list(state.items()):
        stop_loss_id = tracked["stop_loss_order_id"]
        target_price = Decimal(tracked["target_price"])

        try:
            stop_loss_order = client.get_order_by_id(stop_loss_id)
        except APIError as exc:
            raise ExitError(f"Failed to check exit order status for {symbol}") from exc
        stop_loss_status = str(stop_loss_order.status).split(".")[-1].lower()

        if stop_loss_status == "filled":
            actions.append(ReconcileAction(
                symbol=symbol, action="STOP_LOSS_FILLED",
                detail=(
                    f"stop-loss filled at {Decimal(str(stop_loss_order.filled_avg_price)):,} "
                    f"(qty {stop_loss_order.filled_qty})"
                ),
            ))
            remove_protective_orders(symbol)
            continue

        if stop_loss_status in ("canceled", "expired", "rejected"):
            # Orphaned (e.g. manually closed) -- stop tracking, nothing to force.
            remove_protective_orders(symbol)
            continue

        stop_price = Decimal(str(stop_loss_order.stop_price))
        qty = Decimal(str(stop_loss_order.qty))

        try:
            quote_request = CryptoLatestQuoteRequest(symbol_or_symbols=symbol)
            quote = data_client.get_crypto_latest_quote(quote_request)[symbol]
        except APIError as exc:
            raise ExitError(f"Failed to fetch price for {symbol}") from exc
        current_price = Decimal(str(quote.bid_price))

        if current_price >= target_price:
            client.cancel_order_by_id(stop_loss_id)
            client.submit_order(MarketOrderRequest(
                symbol=symbol, qty=qty, side=OrderSide.SELL, time_in_force=TimeInForce.GTC,
            ))
            actions.append(ReconcileAction(
                symbol=symbol, action="TAKE_PROFIT_REALIZED",
                detail=f"price {current_price:,} reached target {target_price:,} -- sold at market",
            ))
            remove_protective_orders(symbol)
            continue

        if current_price <= stop_price:
            client.cancel_order_by_id(stop_loss_id)
            client.submit_order(MarketOrderRequest(
                symbol=symbol, qty=qty, side=OrderSide.SELL, time_in_force=TimeInForce.GTC,
            ))
            actions.append(ReconcileAction(
                symbol=symbol, action="FORCED_MARKET_SELL",
                detail=(
                    f"stop-loss stuck unfilled at price {current_price:,} "
                    f"(trigger {stop_price:,}) -- forced market sell"
                ),
            ))
            remove_protective_orders(symbol)

    return actions


def close_position(client: TradingClient, symbol: str) -> CloseResult:
    """Closes a position on demand. Cancels any tracked stop-loss order
    first -- required, since Alpaca refuses to close a position while a
    sell order still holds its balance (confirmed live: attempting to
    close with the stop-loss still open fails with "insufficient
    balance", the same lockup mechanic as ADR 0005 -- it doesn't
    silently orphan the order, it just blocks the close entirely).

    `symbol` is the slash form (`BTC/USD`, matching order/exit_state
    convention) -- converted to the no-slash form (`BTCUSD`) Alpaca's
    close-by-symbol endpoint actually expects (confirmed live, see
    feature 4's symbol-format note).
    """
    tracked = load_state().get(symbol)
    if tracked:
        try:
            client.cancel_order_by_id(tracked["stop_loss_order_id"])
        except APIError as exc:
            raise ExitError(f"Failed to cancel stop-loss order for {symbol}") from exc
        remove_protective_orders(symbol)

    no_slash_symbol = symbol.replace("/", "")
    try:
        order = client.close_position(no_slash_symbol)
    except APIError as exc:
        raise ExitError(f"Failed to close position for {symbol}") from exc

    order = poll_until_terminal(client, order.id, symbol)

    status_name = str(order.status).split(".")[-1].upper()
    return CloseResult(
        order_id=str(order.id),
        symbol=symbol,
        status=status_name if status_name in ("FILLED", "REJECTED", "CANCELED") else "REJECTED",
        filled_qty=Decimal(str(order.filled_qty)) if order.filled_qty else None,
        filled_avg_price=Decimal(str(order.filled_avg_price)) if order.filled_avg_price else None,
    )


if __name__ == "__main__":
    import logging

    from crypto_bot.config import load_settings

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    settings = load_settings()
    data_client = CryptoHistoricalDataClient(
        api_key=settings.alpaca_api_key, secret_key=settings.alpaca_secret_key
    )
    atr = get_atr(data_client, "BTC/USD")
    print(f"BTC/USD hourly ATR ({DEFAULT_ATR_PERIOD}-period): {atr}")
