"""Parses and executes the small set of Telegram commands this bot
supports. Fixed, explicit command syntax -- no natural-language parsing,
consistent with this project's rule-based-only constraint.
"""

from decimal import Decimal, InvalidOperation

from alpaca.data.historical.crypto import CryptoHistoricalDataClient
from alpaca.trading.client import TradingClient

from crypto_bot.config import Settings
from crypto_bot.exits import RISK_TIER_ATR_MULTIPLIERS, ExitError, close_position
from crypto_bot.orders import OrderError
from crypto_bot.positions import PositionError, get_open_positions
from crypto_bot.trading import TradingError, open_protected_position

DEFAULT_TIER = "moderate"
RISK_TIER_NAMES = set(RISK_TIER_ATR_MULTIPLIERS.keys())

KNOWN_QUOTE_SUFFIXES = ("USDT", "USDC", "USD", "BTC")

WELCOME_TEXT = (
    "This is your Alpaca crypto trading bot (paper account only).\n"
    "\n"
    "How it works:\n"
    "- If auto-entry is enabled, it checks a fixed set of 6 symbols "
    "every 2 minutes for a simple moving-average crossover signal and "
    "buys automatically when it fires.\n"
    "- Every position -- yours or automatic -- gets a stop-loss "
    "attached the moment it opens, sized to current volatility (ATR). "
    "Alpaca enforces it instantly; you'll get a message here once it "
    "fires, or once the take-profit target is realized.\n"
    "- You can also trade manually anytime with the commands below.\n"
    "\n"
    "Commands:\n"
    "/buy SYMBOL [AMOUNT] [TIER] - Buy and protect a symbol. AMOUNT "
    "defaults to the configured per-trade amount; TIER defaults to "
    "moderate (conservative/moderate/aggressive).\n"
    "/close SYMBOL - Close an open position.\n"
    "/positions - List open positions.\n"
    "/help - Show this message again."
)

HELP_TEXT = WELCOME_TEXT


def _normalize_symbol(raw: str) -> str:
    """Accepts a symbol with or without a slash (`BTC/USD` or `BTCUSD`)
    and returns the slash form the underlying functions expect.
    """
    symbol = raw.strip().upper()
    if "/" in symbol:
        return symbol
    for quote in KNOWN_QUOTE_SUFFIXES:
        if symbol.endswith(quote) and len(symbol) > len(quote):
            return f"{symbol[: -len(quote)]}/{quote}"
    return symbol


def _buy_button_label(settings: Settings) -> str:
    return f"Buy {settings.default_order_symbol} (${settings.default_order_notional})"


def _buy_button_prefix(settings: Settings) -> str:
    return f"buy {settings.default_order_symbol.lower()} ("


def _main_keyboard(settings: Settings) -> dict:
    return {
        "keyboard": [[_buy_button_label(settings)], ["Positions"]],
        "resize_keyboard": True,
    }


def handle_command(
    client: TradingClient, data_client: CryptoHistoricalDataClient, settings: Settings, text: str
) -> tuple[str, dict | None]:
    """Returns `(reply_text, reply_markup)`. Recognizes both `/slash`
    commands and the plain-text button labels from `_main_keyboard()`.
    """
    normalized = text.strip()
    lowered = normalized.lower()

    if not normalized:
        return HELP_TEXT, _main_keyboard(settings)
    if lowered in ("/start", "start", "/help", "help"):
        return WELCOME_TEXT, _main_keyboard(settings)
    if lowered in ("/positions", "positions"):
        return _handle_positions(client), None
    if lowered.startswith(_buy_button_prefix(settings)):
        return (
            _execute_buy(
                client,
                data_client,
                settings.default_order_symbol,
                settings.default_order_notional,
                DEFAULT_TIER,
            ),
            None,
        )

    parts = normalized.split()
    command, args = parts[0].lower(), parts[1:]

    if command == "/buy":
        return _handle_buy_command(client, data_client, settings, args), None
    if command == "/close":
        return _handle_close(client, args), None

    return HELP_TEXT, _main_keyboard(settings)


def _handle_buy_command(
    client: TradingClient, data_client: CryptoHistoricalDataClient, settings: Settings, args: list[str]
) -> str:
    if not args:
        return "Usage: /buy SYMBOL [AMOUNT] [TIER]"

    symbol = _normalize_symbol(args[0])
    amount = settings.default_order_notional
    tier = DEFAULT_TIER

    if len(args) > 1:
        try:
            amount = Decimal(args[1])
        except InvalidOperation:
            return f"amount must be a number, got {args[1]!r}"

    if len(args) > 2:
        tier = args[2]
        if tier not in RISK_TIER_NAMES:
            return f"Unknown tier {tier!r}. Must be one of {sorted(RISK_TIER_NAMES)}."

    return _execute_buy(client, data_client, symbol, amount, tier)


def _execute_buy(
    client: TradingClient,
    data_client: CryptoHistoricalDataClient,
    symbol: str,
    amount: Decimal,
    tier: str,
) -> str:
    try:
        opened = open_protected_position(client, data_client, symbol, amount, tier)
    except (TradingError, OrderError) as exc:
        return f"Buy failed: {exc}"

    return (
        f"Bought {opened.order.filled_qty} {symbol} at {opened.order.filled_avg_price} "
        f"(tier={tier}, stop={opened.protective_orders.stop_price}, "
        f"target={opened.protective_orders.target_price})"
    )


def _handle_close(client: TradingClient, args: list[str]) -> str:
    if not args:
        return "Usage: /close SYMBOL"

    symbol = _normalize_symbol(args[0])
    try:
        result = close_position(client, symbol)
    except (ExitError, OrderError) as exc:
        return f"Close failed: {exc}"

    return f"Closed {result.symbol}: {result.status}, qty={result.filled_qty} @ {result.filled_avg_price}"


def _handle_positions(client: TradingClient) -> str:
    try:
        positions = get_open_positions(client)
    except PositionError as exc:
        return f"Failed to fetch positions: {exc}"

    if not positions:
        return "No open positions."

    return "\n\n".join(
        f"{p.symbol}  qty={p.qty}  entry=${p.avg_entry_price}  pl=${p.unrealized_pl}"
        for p in positions
    )
