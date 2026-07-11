"""Loads and validates configuration from environment variables."""

import os
from dataclasses import dataclass
from decimal import Decimal

from dotenv import load_dotenv


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""


PAPER_BASE_URL = "https://paper-api.alpaca.markets"
LIVE_BASE_URL = "https://api.alpaca.markets"


@dataclass(frozen=True)
class Settings:
    alpaca_api_key: str
    alpaca_secret_key: str
    alpaca_paper: bool
    alpaca_base_url: str
    auto_entry_enabled: bool
    auto_entry_notional: Decimal
    auto_entry_total_cap: Decimal
    auto_entry_daily_cap: Decimal
    telegram_bot_token: str
    telegram_chat_id: str
    default_order_notional: Decimal
    default_order_symbol: str


def _parse_bool(value: str) -> bool:
    return value.strip().lower() not in ("false", "0", "no")


def load_settings() -> Settings:
    """Load settings from environment variables (via .env if present).

    `ALPACA_API_KEY`/`ALPACA_SECRET_KEY`/`ALPACA_BASE_URL` are required.
    `ALPACA_PAPER` defaults to `True` -- must be set explicitly to
    `false` for any live-account behavior (see ADR 0003).

    `ALPACA_BASE_URL` is required, not inferred from `ALPACA_PAPER`, as a
    deliberate fail-safe: it must match `ALPACA_PAPER`'s expected host
    (`PAPER_BASE_URL`/`LIVE_BASE_URL`) exactly, or loading raises rather
    than silently trading against the wrong environment. Two separately
    set values agreeing is what makes this a real check rather than one
    value inferring the other.

    `AUTO_ENTRY_ENABLED` defaults to `False` -- must be set explicitly to
    `true` before the cron cycle will place any automatic trade (feature
    9). `AUTO_ENTRY_NOTIONAL` defaults to `"10"` (Alpaca's crypto minimum
    notional) if unset -- a fallback, not a recommendation; see feature
    9's spec for the user's actual configured value.

    `AUTO_ENTRY_TOTAL_CAP`/`AUTO_ENTRY_DAILY_CAP` (ADR 0006) default to
    `"1000"`/`"200"`. Each is both the on/off switch and the limit: `0`
    disables that cap, any value `> 0` enables it at that dollar amount.
    Scoped to auto-entry only -- never applies to manual trades.

    `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`/`DEFAULT_ORDER_NOTIONAL` are
    required (feature 10) -- loading fails fast if any is missing, same
    posture as the Alpaca credentials. `DEFAULT_ORDER_SYMBOL` defaults to
    `"BTC/USD"` if unset.
    """
    load_dotenv()

    alpaca_api_key = os.environ.get("ALPACA_API_KEY")
    alpaca_secret_key = os.environ.get("ALPACA_SECRET_KEY")
    alpaca_base_url = os.environ.get("ALPACA_BASE_URL")

    if not alpaca_api_key:
        raise ConfigError("ALPACA_API_KEY is required but not set")
    if not alpaca_secret_key:
        raise ConfigError("ALPACA_SECRET_KEY is required but not set")
    if not alpaca_base_url:
        raise ConfigError("ALPACA_BASE_URL is required but not set")

    telegram_bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    default_order_notional_raw = os.environ.get("DEFAULT_ORDER_NOTIONAL")

    if not telegram_bot_token:
        raise ConfigError("TELEGRAM_BOT_TOKEN is required but not set")
    if not telegram_chat_id:
        raise ConfigError("TELEGRAM_CHAT_ID is required but not set")
    if not default_order_notional_raw:
        raise ConfigError("DEFAULT_ORDER_NOTIONAL is required but not set")

    alpaca_paper = _parse_bool(os.environ.get("ALPACA_PAPER") or "true")
    expected_base_url = PAPER_BASE_URL if alpaca_paper else LIVE_BASE_URL

    if alpaca_base_url != expected_base_url:
        raise ConfigError(
            f"ALPACA_BASE_URL ({alpaca_base_url!r}) does not match "
            f"ALPACA_PAPER={alpaca_paper} -- expected {expected_base_url!r}. "
            "Refusing to start rather than risk trading against the wrong "
            "environment."
        )

    auto_entry_enabled = _parse_bool(os.environ.get("AUTO_ENTRY_ENABLED") or "false")
    auto_entry_notional = Decimal(os.environ.get("AUTO_ENTRY_NOTIONAL") or "10")
    auto_entry_total_cap = Decimal(os.environ.get("AUTO_ENTRY_TOTAL_CAP") or "1000")
    auto_entry_daily_cap = Decimal(os.environ.get("AUTO_ENTRY_DAILY_CAP") or "200")
    default_order_notional = Decimal(default_order_notional_raw)
    default_order_symbol = os.environ.get("DEFAULT_ORDER_SYMBOL") or "BTC/USD"

    return Settings(
        alpaca_api_key=alpaca_api_key,
        alpaca_secret_key=alpaca_secret_key,
        alpaca_paper=alpaca_paper,
        alpaca_base_url=alpaca_base_url,
        auto_entry_enabled=auto_entry_enabled,
        auto_entry_notional=auto_entry_notional,
        auto_entry_total_cap=auto_entry_total_cap,
        auto_entry_daily_cap=auto_entry_daily_cap,
        telegram_bot_token=telegram_bot_token,
        telegram_chat_id=telegram_chat_id,
        default_order_notional=default_order_notional,
        default_order_symbol=default_order_symbol,
    )
