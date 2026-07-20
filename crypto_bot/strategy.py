"""Automated entry strategy: decides *when* to open a position, using a
Bollinger Band squeeze-breakout signal on hourly bars, across a fixed,
deliberately curated list of 6 symbols. See spec 009 and its 2026-07-13
amendment for why this replaced the original 5/20 SMA crossover, and
`LOCAL_NOTES.md` (gitignored, local machine only) for the full multi-
window backtest record behind the decision.

Signal: John Bollinger's Bollinger Bands (1980s) combined with the "TTM
Squeeze" concept popularized by John Carter ("Mastering the Trade",
2006) -- a low-volatility contraction (Bollinger Bands sitting fully
inside the Keltner Channel) followed by the bands expanding back outside
it signals an imminent directional move. Enter only on the hour that
release happens, and only if price is above the basis line (confirms
upward direction, not downward).

Every entry goes through `trading.open_protected_position` (feature 8)
-- the same function a manual Telegram `/buy` command calls -- so an
auto-entered position gets its stop-loss attached the instant it opens,
exactly like a manual one.
"""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

from alpaca.common.exceptions import APIError
from alpaca.data.historical.crypto import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest, CryptoLatestQuoteRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient

from crypto_bot.auto_entry_spend import effective_daily_spent, load_state, record_spend, save_state
from crypto_bot.positions import get_open_positions
from crypto_bot.trading import TradingError, open_protected_position

AUTO_ENTRY_SYMBOLS = ["BTC/USD", "ETH/USD", "AAVE/USD", "UNI/USD", "PAXG/USD", "XRP/USD"]

BB_PERIOD = 20
BB_STD_MULTIPLIER = Decimal("2")
KC_ATR_PERIOD = 14
KC_ATR_MULTIPLIER = Decimal("1.5")
# Need BB_PERIOD bars for the *prior* hour's rolling window, plus one more
# bar for the *current* hour's window, to detect a squeeze-on -> squeeze-off
# transition rather than a single-hour snapshot.
MIN_HOURLY_BARS = BB_PERIOD + 1
DEFAULT_HOURLY_FETCH_COUNT = 30


class StrategyError(Exception):
    """Raised when Alpaca rejects or fails a bars/account/quote request."""


def get_recent_hourly_bars(
    data_client: CryptoHistoricalDataClient, symbol: str, count: int = DEFAULT_HOURLY_FETCH_COUNT
) -> list:
    """Fetches the last `count` *complete* hourly bars, oldest-to-newest.

    Same still-forming-bar exclusion as the project's other bar fetches
    (`exits.get_atr`, the prior `get_recent_closes`) -- Alpaca includes
    the current, still-accumulating hour as the last element.
    """
    request = CryptoBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Hour,
        start=datetime.now(timezone.utc) - timedelta(hours=count + 2),
    )
    try:
        bars = data_client.get_crypto_bars(request).data.get(symbol, [])
    except APIError as exc:
        raise StrategyError(f"Failed to fetch hourly bars for {symbol}") from exc

    now = datetime.now(timezone.utc)
    complete = [b for b in bars if b.timestamp + timedelta(hours=1) <= now]
    return complete[-count:]


def _latest_price(data_client: CryptoHistoricalDataClient, symbol: str) -> Decimal:
    """Live bid price as "current price" -- mirrors the same convention
    `exits.check_and_reconcile_exits` already uses for threshold checks.
    """
    try:
        quote = data_client.get_crypto_latest_quote(
            CryptoLatestQuoteRequest(symbol_or_symbols=symbol)
        )[symbol]
    except APIError as exc:
        raise StrategyError(f"Failed to fetch latest price for {symbol}") from exc
    return Decimal(str(quote.bid_price))


def _bollinger_middle_bands(closes: list[Decimal]) -> tuple[Decimal, Decimal, Decimal]:
    """Middle/upper/lower Bollinger Bands over the trailing BB_PERIOD closes."""
    window = closes[-BB_PERIOD:]
    middle = sum(window) / BB_PERIOD
    variance = sum((c - middle) ** 2 for c in window) / BB_PERIOD
    std = variance.sqrt()
    return middle, middle + BB_STD_MULTIPLIER * std, middle - BB_STD_MULTIPLIER * std


def _atr(bars: list) -> Decimal:
    """Plain rolling mean of true range over the trailing KC_ATR_PERIOD
    bars -- same formula as `exits.get_atr`, reimplemented locally since
    this strategy needs it at two different points in time (the prior
    complete hour and the latest one), not just "right now".
    """
    window = bars[-(KC_ATR_PERIOD + 1) :]
    prev_close = Decimal(str(window[0].close))
    true_ranges = []
    for bar in window[1:]:
        high, low, close = Decimal(str(bar.high)), Decimal(str(bar.low)), Decimal(str(bar.close))
        true_ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
        prev_close = close
    return sum(true_ranges) / KC_ATR_PERIOD


def _squeeze_on(closes: list[Decimal], bars: list) -> bool:
    """True when Bollinger Bands sit fully inside the Keltner Channel --
    the low-volatility contraction that precedes a breakout."""
    _, upper_bb, lower_bb = _bollinger_middle_bands(closes)
    atr = _atr(bars)
    middle = sum(closes[-BB_PERIOD:]) / BB_PERIOD
    upper_kc = middle + KC_ATR_MULTIPLIER * atr
    lower_kc = middle - KC_ATR_MULTIPLIER * atr
    return lower_bb > lower_kc and upper_bb < upper_kc


def check_entry_signal(hourly_bars: list, current_price: Decimal) -> bool:
    """True only on the hour a squeeze has just released -- squeeze was ON
    as of the prior complete hour and is OFF as of the latest complete
    hour -- with `current_price` above the latest basis (middle) line,
    confirming an upward breakout rather than a downward one.
    """
    if len(hourly_bars) < MIN_HOURLY_BARS:
        return False

    closes = [Decimal(str(b.close)) for b in hourly_bars]

    squeeze_was_on = _squeeze_on(closes[:-1], hourly_bars[:-1])
    squeeze_is_on = _squeeze_on(closes, hourly_bars)
    released = squeeze_was_on and not squeeze_is_on

    middle, _, _ = _bollinger_middle_bands(closes)
    return released and current_price > middle


@dataclass(frozen=True)
class AutoEntryResult:
    symbol: str
    action: Literal[
        "ENTERED",
        "SKIPPED_ALREADY_OPEN",
        "SKIPPED_TOTAL_CAP_REACHED",
        "SKIPPED_DAILY_CAP_REACHED",
        "SKIPPED_NO_SIGNAL",
        "SKIPPED_INSUFFICIENT_FUNDS",
        "ORDER_NOT_FILLED",
    ]
    detail: str
    # True only on the cycle a cap transitions from not-blocking to
    # blocking (feature 11) -- run_cycle.py notifies on this, not on
    # every repeat SKIPPED_TOTAL_CAP_REACHED/SKIPPED_DAILY_CAP_REACHED
    # while still capped.
    notify: bool = False


def _crypto_buying_power(client: TradingClient) -> Decimal:
    """Alpaca crypto trading is spot/cash-only (no margin) -- `buying_power`
    on the account is inflated by the equities margin multiplier (confirmed
    live 2026-07-11: buying_power was 4x cash on a paper account).
    `non_marginable_buying_power` is the real cash-backed figure, correct
    for a crypto affordability check.
    """
    try:
        account = client.get_account()
    except APIError as exc:
        raise StrategyError("Failed to fetch account buying power") from exc
    return Decimal(str(account.non_marginable_buying_power))


def run_auto_entry_check(
    client: TradingClient,
    data_client: CryptoHistoricalDataClient,
    symbol: str,
    notional: Decimal,
    total_cap: Decimal = Decimal("0"),
    daily_cap: Decimal = Decimal("0"),
) -> AutoEntryResult:
    """`total_cap`/`daily_cap` are optional spending caps on top of the
    live buying-power check below (ADR 0006) -- `0` disables a cap
    entirely. Scoped to auto-entry only; manual trades are never gated
    by either.
    """
    no_slash_symbol = symbol.replace("/", "")
    positions = get_open_positions(client)
    if any(p.symbol == no_slash_symbol for p in positions):
        return AutoEntryResult(symbol, "SKIPPED_ALREADY_OPEN", "")

    today = datetime.now(timezone.utc).date()
    spend_state = load_state()

    was_total_notified = spend_state.total_cap_notified
    total_capped = total_cap > 0 and spend_state.total_spent + notional > total_cap
    if total_capped != was_total_notified:
        spend_state = replace(spend_state, total_cap_notified=total_capped)
        save_state(spend_state)
    if total_capped:
        return AutoEntryResult(
            symbol,
            "SKIPPED_TOTAL_CAP_REACHED",
            f"total_spent=${spend_state.total_spent:,} cap=${total_cap:,}",
            notify=not was_total_notified,
        )

    daily_spent = effective_daily_spent(spend_state, today)
    was_daily_notified = spend_state.daily_cap_notified
    daily_capped = daily_cap > 0 and daily_spent + notional > daily_cap
    if daily_capped != was_daily_notified:
        spend_state = replace(spend_state, daily_cap_notified=daily_capped)
        save_state(spend_state)
    if daily_capped:
        return AutoEntryResult(
            symbol,
            "SKIPPED_DAILY_CAP_REACHED",
            f"daily_spent=${daily_spent:,} cap=${daily_cap:,}",
            notify=not was_daily_notified,
        )

    hourly_bars = get_recent_hourly_bars(data_client, symbol)
    current_price = _latest_price(data_client, symbol)
    if not check_entry_signal(hourly_bars, current_price):
        return AutoEntryResult(symbol, "SKIPPED_NO_SIGNAL", "")

    available = _crypto_buying_power(client)
    if available < notional:
        return AutoEntryResult(
            symbol,
            "SKIPPED_INSUFFICIENT_FUNDS",
            f"available=${available:,} required=${notional:,}",
        )

    try:
        opened = open_protected_position(client, data_client, symbol, notional, "moderate")
    except TradingError as exc:
        return AutoEntryResult(symbol, "ORDER_NOT_FILLED", str(exc))

    save_state(record_spend(spend_state, notional, today))

    return AutoEntryResult(
        symbol,
        "ENTERED",
        f"filled {opened.order.filled_qty} @ {opened.order.filled_avg_price:,}",
    )


def run_auto_entry_cycle(
    client: TradingClient, data_client: CryptoHistoricalDataClient, settings
) -> list[AutoEntryResult]:
    return [
        run_auto_entry_check(
            client,
            data_client,
            symbol,
            settings.auto_entry_notional,
            settings.auto_entry_total_cap,
            settings.auto_entry_daily_cap,
        )
        for symbol in AUTO_ENTRY_SYMBOLS
    ]
