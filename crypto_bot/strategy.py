"""Automated entry strategy: decides *when* to open a position, using a
plain rule-based signal (5/20-period SMA crossover on 5-minute bars)
across a fixed, deliberately curated list of 6 symbols. See spec 009 for
why these symbols and why a live buying-power check instead of a
locally-tracked budget counter.

Every entry goes through `trading.open_protected_position` (feature 8)
-- the same function a manual Telegram `/buy` command calls -- so an
auto-entered position gets its stop-loss attached the instant it opens,
exactly like a manual one.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

from alpaca.common.exceptions import APIError
from alpaca.data.historical.crypto import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.trading.client import TradingClient

from crypto_bot.auto_entry_spend import effective_daily_spent, load_state, record_spend, save_state
from crypto_bot.positions import get_open_positions
from crypto_bot.trading import TradingError, open_protected_position

AUTO_ENTRY_SYMBOLS = ["BTC/USD", "ETH/USD", "AAVE/USD", "UNI/USD", "PAXG/USD", "XRP/USD"]

BAR_TIMEFRAME = TimeFrame(5, TimeFrameUnit.Minute)
BAR_DURATION = timedelta(minutes=5)
DEFAULT_CLOSES_COUNT = 20


class StrategyError(Exception):
    """Raised when Alpaca rejects or fails a bars/account request."""


def get_recent_closes(
    data_client: CryptoHistoricalDataClient, symbol: str, count: int = DEFAULT_CLOSES_COUNT
) -> list[Decimal]:
    """Fetches the last `count` *complete* 5-minute bars' close prices,
    oldest-to-newest.

    Alpaca returns the current, still-accumulating bar as the last
    element of the series with an artificially low volume/partial data
    (confirmed live 2026-07-11) -- it must be dropped, or a misleadingly
    volatile partial candle feeds into the average.
    """
    request = CryptoBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=BAR_TIMEFRAME,
        start=datetime.now(timezone.utc) - (BAR_DURATION * (count + 2)),
    )
    try:
        bars = data_client.get_crypto_bars(request).data.get(symbol, [])
    except APIError as exc:
        raise StrategyError(f"Failed to fetch bars for {symbol}") from exc

    now = datetime.now(timezone.utc)
    complete = [b for b in bars if b.timestamp + BAR_DURATION <= now]
    return [Decimal(str(b.close)) for b in complete[-count:]]


def check_entry_signal(closes: list[Decimal]) -> bool:
    if len(closes) < DEFAULT_CLOSES_COUNT:
        return False
    fast = sum(closes[-5:]) / 5
    slow = sum(closes[-DEFAULT_CLOSES_COUNT:]) / DEFAULT_CLOSES_COUNT
    return fast > slow


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

    if total_cap > 0 and spend_state.total_spent + notional > total_cap:
        return AutoEntryResult(
            symbol,
            "SKIPPED_TOTAL_CAP_REACHED",
            f"total_spent=${spend_state.total_spent} cap=${total_cap}",
        )

    daily_spent = effective_daily_spent(spend_state, today)
    if daily_cap > 0 and daily_spent + notional > daily_cap:
        return AutoEntryResult(
            symbol,
            "SKIPPED_DAILY_CAP_REACHED",
            f"daily_spent=${daily_spent} cap=${daily_cap}",
        )

    closes = get_recent_closes(data_client, symbol)
    if not check_entry_signal(closes):
        return AutoEntryResult(symbol, "SKIPPED_NO_SIGNAL", "")

    available = _crypto_buying_power(client)
    if available < notional:
        return AutoEntryResult(
            symbol,
            "SKIPPED_INSUFFICIENT_FUNDS",
            f"available=${available} required=${notional}",
        )

    try:
        opened = open_protected_position(client, data_client, symbol, notional, "moderate")
    except TradingError as exc:
        return AutoEntryResult(symbol, "ORDER_NOT_FILLED", str(exc))

    save_state(record_spend(spend_state, notional, today))

    return AutoEntryResult(
        symbol,
        "ENTERED",
        f"filled {opened.order.filled_qty} @ {opened.order.filled_avg_price}",
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
