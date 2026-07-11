# Feature: Automated entry strategy

Status: Done
Depends on: [003-fetch-live-price-data](003-fetch-live-price-data.md), [004-place-market-order](004-place-market-order.md), [005-monitor-open-positions](005-monitor-open-positions.md), [006-stop-loss-take-profit](006-stop-loss-take-profit.md), [008-manual-close-and-safe-open](008-manual-close-and-safe-open.md)
Related ADRs: [0006-optional-auto-entry-spending-caps](../adr/0006-optional-auto-entry-spending-caps.md)

## Summary

Decides *when* to open a position automatically, using a plain rule-
based signal (moving average crossover) — the piece every prior feature
assumed a human provides by typing a command or tapping a button. Runs
on the same 2-minute cron cadence as feature 6's exit reconciliation
check (feature 7), across a fixed, deliberately curated list of 6
symbols (not a generic multi-instrument framework — see Non-Goals):

**`BTC/USD`, `ETH/USD`, `AAVE/USD`, `UNI/USD`, `PAXG/USD`, `XRP/USD`.**

This list was chosen 2026-07-11 from Alpaca's full 73-pair tradable
universe (see `specs/context/platform-decision.md`'s 2026-07-11
correction), ranked by live 24h Alpaca dollar volume, excluding
stablecoin-pegged pairs (USDC/USD, USDT/USD have no real volatility to
trade) and excluding DOGE/USD and XRP/USD from the *ranking-driven*
picks specifically at the user's request (DOGE: considered low-quality;
XRP: the user already holds positions independently and specifically
asked for it to be added on top of the volume-ranked top 5, not because
it ranked there — it actually ranks #7 by volume, just below PAXG/USD
and SOL/USD). PAXG (a gold-backed token, much lower volatility than the
other 5) was kept deliberately as the one stable name in an otherwise
volatile set — confirmed with the user, not a stray inclusion.

Every prior feature (4, 5, 6, 8) already exists and is reused as-is:
this feature is the signal-and-gate logic that decides *when* to call
`trading.open_protected_position` (feature 8) automatically, the same
function a future Telegram `/buy` command will call for manual entries.

## Goals

- A pure signal function: given recent closing prices for a symbol,
  decide if the "fast average above slow average" buy condition is
  currently true.
- Use Alpaca's own historical crypto bar data (5-minute bars) to compute
  the averages — no local price-history storage needed, consistent with
  this project's no-persistence approach elsewhere (feature 6's ATR
  calculation works the same way, just with hourly bars).
- Check all 6 configured symbols independently each cron cycle; only
  enter a symbol if there's no existing open position for it already —
  this is what prevents re-buying every 2 minutes while the signal
  condition continues to hold, without needing to remember "did I
  already act on this crossover" between runs.
- Gate every auto-entry attempt with a **live check against real
  account funds** (Alpaca's own reported non-marginable/crypto buying
  power) immediately before placing the order — per this project's hard
  constraint (`specs/context/constraints.md`): no locally-tracked
  spending counter, no preset dollar ceiling, just "can the account
  actually afford this trade right now."
- Require an explicit, default-off enable switch
  (`AUTO_ENTRY_ENABLED=true`) before the cron job will place any
  automatic trade — deploying this feature must not silently turn on
  unattended spending on the Pi. Confirmed with the user (2026-07-11):
  this is a second explicit gate alongside the existing paper/live
  gate, not a replacement for it.
- Auto-triggered entries always use the `moderate` risk tier (feature 6)
  and go through `open_protected_position` (feature 8) — no prompt,
  since nothing is waiting on a person to answer, and every position
  gets its stop-loss attached the instant it opens regardless of how it
  was opened.

## Non-Goals

- No configurable/generic multi-instrument framework — the 6-symbol
  list above is a hardcoded constant reflecting a deliberate, curated
  choice made in conversation, not a `.env`-configurable list. Making it
  configurable is future work if the user asks (see Out of Scope).
- No other entry signals (RSI, breakout, etc.) — 5/20-period SMA
  crossover only, for now.
- No selling/shorting signal — this feature only decides long entries
  (Alpaca crypto is spot-only per feature 8's `open_protected_position`
  docstring); exits remain entirely feature 6's job (SL/TP), regardless
  of how a position was opened.
- No backtesting of the strategy — it runs live against current data
  only.
- ~~No locally-persisted spending counter/budget cap~~ **Amended
  2026-07-11, see ADR 0006**: two *optional* locally-persisted spending
  caps (total, daily) were added on top of the live buying-power check,
  at the user's explicit request. The live check remains the primary,
  always-on gate; the caps are additive, off individually via `0`, and
  scoped to auto-entry only.
- No per-symbol notional override — all 6 symbols use the same
  `AUTO_ENTRY_NOTIONAL` per-trade amount.
- No Telegram integration in this feature — sending a notification when
  auto-entry acts is feature 10's job (which depends on this feature
  existing first, per the user's explicit sequencing: auto-entry and
  auto-exit are "the two main features" and come before the Telegram
  wrapper).

## Requirements

1. `crypto_bot/strategy.py` exposes:
   - `AUTO_ENTRY_SYMBOLS: list[str] = ["BTC/USD", "ETH/USD", "AAVE/USD", "UNI/USD", "PAXG/USD", "XRP/USD"]`
     — the fixed symbol list (Summary).
   - `get_recent_closes(data_client, symbol, count=20) -> list[Decimal]`
     — fetches the last `count` **complete** 5-minute bars via
     `CryptoBarsRequest(timeframe=TimeFrame(5, TimeFrameUnit.Minute))`
     and returns their close prices, oldest-to-newest. Must drop a
     still-forming trailing bar (its `timestamp + 5 minutes > now`) —
     confirmed live (2026-07-11) that Alpaca returns the current,
     still-accumulating bar as the last element with an
     artificially-low volume/partial data, the same issue found while
     computing this feature's symbol-ranking numbers; including it
     would feed a misleadingly volatile partial candle into the
     average.
   - `check_entry_signal(closes: list[Decimal]) -> bool` — `True` if the
     mean of the last 5 closes is greater than the mean of the last 20
     closes; `False` if fewer than 20 closes are available.
2. `crypto_bot/strategy.py` also exposes:
   - `AutoEntryResult` (frozen dataclass): `symbol: str`, `action:
     Literal["ENTERED", "SKIPPED_ALREADY_OPEN", "SKIPPED_NO_SIGNAL",
     "SKIPPED_INSUFFICIENT_FUNDS", "ORDER_NOT_FILLED"]`, `detail: str`.
   - `run_auto_entry_check(client, data_client, symbol) ->
     AutoEntryResult`:
     1. Skip (`SKIPPED_ALREADY_OPEN`) if a position is already open for
        `symbol` (via feature 5's `get_open_positions`, matching the
        no-slash symbol form the same way `trading.py` already does).
     2. Fetch recent closes, run `check_entry_signal`. Skip
        (`SKIPPED_NO_SIGNAL`) if `False`.
     3. Fetch the account's current crypto-eligible buying power (see
        Design — `non_marginable_buying_power`, not `buying_power` or
        `cash`). Skip (`SKIPPED_INSUFFICIENT_FUNDS`) if it's less than
        `settings.auto_entry_notional`.
     4. Otherwise call `open_protected_position(client, data_client,
        symbol, settings.auto_entry_notional, "moderate")` (feature 8).
        If it raises `TradingError` (order didn't fill), return
        `ORDER_NOT_FILLED` with the error as `detail` instead of
        propagating.
     5. Return `ENTERED` with a detail summarizing fill price/qty.
   - `run_auto_entry_cycle(client, data_client, settings) ->
     list[AutoEntryResult]` — calls `run_auto_entry_check` once per
     symbol in `AUTO_ENTRY_SYMBOLS`, returns all 6 results. Does **not**
     itself check `settings.auto_entry_enabled` — see Requirement 4.
3. `crypto_bot/config.py`'s `Settings` gains:
   - `auto_entry_enabled: bool` (from `AUTO_ENTRY_ENABLED`, default
     `false` — same `_parse_bool` helper `alpaca_paper` already uses).
   - `auto_entry_notional: Decimal` (from `AUTO_ENTRY_NOTIONAL`, default
     `"10"` — Alpaca's crypto minimum notional, the value confirmed with
     the user 2026-07-11).
4. `crypto_bot/run_cycle.py`'s reconcile entrypoint (feature 7) gains an
   auto-entry step, run **before** the existing exit reconciliation
   check each cycle: if `settings.auto_entry_enabled`, call
   `run_auto_entry_cycle` and log each `AutoEntryResult`; if disabled,
   skip the step entirely (log nothing, no API calls made) — the
   enable-gate check happens here in `run_cycle.py`, not inside
   `strategy.py`, so `run_auto_entry_cycle`/`run_auto_entry_check` stay
   simple and directly testable without needing a `Settings` toggle
   threaded through their own logic.

## Design / Approach

```python
# crypto_bot/strategy.py
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from typing import Literal

from alpaca.common.exceptions import APIError
from alpaca.data.historical.crypto import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.trading.client import TradingClient

from crypto_bot.positions import get_open_positions
from crypto_bot.trading import TradingError, open_protected_position

AUTO_ENTRY_SYMBOLS = ["BTC/USD", "ETH/USD", "AAVE/USD", "UNI/USD", "PAXG/USD", "XRP/USD"]

BAR_TIMEFRAME = TimeFrame(5, TimeFrameUnit.Minute)


class StrategyError(Exception):
    """Raised when Alpaca rejects or fails a bars/account request."""


def get_recent_closes(
    data_client: CryptoHistoricalDataClient, symbol: str, count: int = 20
) -> list[Decimal]:
    request = CryptoBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=BAR_TIMEFRAME,
        start=datetime.now(timezone.utc) - timedelta(minutes=5 * (count + 2)),
    )
    try:
        bars = data_client.get_crypto_bars(request).data.get(symbol, [])
    except APIError as exc:
        raise StrategyError(f"Failed to fetch bars for {symbol}") from exc

    now = datetime.now(timezone.utc)
    complete = [b for b in bars if b.timestamp + timedelta(minutes=5) <= now]
    return [Decimal(str(b.close)) for b in complete[-count:]]


def check_entry_signal(closes: list[Decimal]) -> bool:
    if len(closes) < 20:
        return False
    fast = sum(closes[-5:]) / 5
    slow = sum(closes[-20:]) / 20
    return fast > slow
```

```python
@dataclass(frozen=True)
class AutoEntryResult:
    symbol: str
    action: Literal[
        "ENTERED", "SKIPPED_ALREADY_OPEN", "SKIPPED_NO_SIGNAL",
        "SKIPPED_INSUFFICIENT_FUNDS", "ORDER_NOT_FILLED",
    ]
    detail: str


def _crypto_buying_power(client: TradingClient) -> Decimal:
    """Alpaca crypto trading is spot/cash-only (no margin) -- `buying_power`
    on the account is inflated by the equities margin multiplier (confirmed
    live 2026-07-11: buying_power was 4x cash on a paper account).
    `non_marginable_buying_power` is the real cash-backed figure, correct
    for a crypto affordability check.
    """
    account = client.get_account()
    return Decimal(str(account.non_marginable_buying_power))


def run_auto_entry_check(
    client: TradingClient, data_client: CryptoHistoricalDataClient,
    symbol: str, notional: Decimal,
) -> AutoEntryResult:
    no_slash_symbol = symbol.replace("/", "")
    positions = get_open_positions(client)
    if any(p.symbol == no_slash_symbol for p in positions):
        return AutoEntryResult(symbol, "SKIPPED_ALREADY_OPEN", "")

    closes = get_recent_closes(data_client, symbol)
    if not check_entry_signal(closes):
        return AutoEntryResult(symbol, "SKIPPED_NO_SIGNAL", "")

    available = _crypto_buying_power(client)
    if available < notional:
        return AutoEntryResult(
            symbol, "SKIPPED_INSUFFICIENT_FUNDS",
            f"available=${available} required=${notional}",
        )

    try:
        opened = open_protected_position(client, data_client, symbol, notional, "moderate")
    except TradingError as exc:
        return AutoEntryResult(symbol, "ORDER_NOT_FILLED", str(exc))

    return AutoEntryResult(
        symbol, "ENTERED",
        f"filled {opened.order.filled_qty} @ {opened.order.filled_avg_price}",
    )


def run_auto_entry_cycle(
    client: TradingClient, data_client: CryptoHistoricalDataClient, settings,
) -> list["AutoEntryResult"]:
    return [
        run_auto_entry_check(client, data_client, symbol, settings.auto_entry_notional)
        for symbol in AUTO_ENTRY_SYMBOLS
    ]
```

`run_cycle.py`'s `__main__` (extending feature 7) becomes: if
`settings.auto_entry_enabled`, run `run_auto_entry_cycle` and log each
result; then run the existing `check_and_reconcile_exits` step
unchanged.

## Environment Variables / Config

- `AUTO_ENTRY_ENABLED` — new, optional, defaults `false`. Must be set to
  `true` for the cron cycle to place any automatic trade.
- `AUTO_ENTRY_NOTIONAL` — new, optional, defaults `"10"` in code
  (Alpaca's crypto minimum notional) if unset — a fallback, not a
  recommendation. Applied per symbol per triggered entry, not a
  total/aggregate cap. **The user's actual `.env` value for paper
  trading is `100`** (confirmed 2026-07-11) — per this project's "no
  preset dollar ceiling" constraint, a specific figure that comes up in
  conversation is the user's own expected usage, not a number to change
  the code default to. `.env.example` ships the `"10"` fallback with a
  comment noting it's a floor, not a suggestion.
- `AUTO_ENTRY_TOTAL_CAP` — new (2026-07-11, ADR 0006), optional, defaults
  `"1000"`. `0` disables the total cap entirely; any value `> 0` is the
  lifetime cumulative dollar ceiling on auto-entry spend. Enabled by
  default once auto-entry itself is on (unlike `AUTO_ENTRY_ENABLED`,
  which defaults off).
- `AUTO_ENTRY_DAILY_CAP` — new (2026-07-11, ADR 0006), optional, defaults
  `"200"`. Same `0`-disables / `>0`-is-the-cap pattern, but resets
  automatically each UTC calendar day.

## Acceptance Criteria

- [x] `check_entry_signal` returns `True`/`False` correctly for
      hand-constructed close-price lists (fast avg above/below/equal to
      slow avg) — unit-tested, no network.
- [x] `check_entry_signal` returns `False` when fewer than 20 closes are
      given.
- [x] `get_recent_closes` parses a mocked bars response into an ordered
      list of `Decimal` closes, and excludes a trailing bar whose
      5-minute window hasn't fully elapsed yet — unit-tested with a
      synthetic "current, still-forming" bar in the mocked response.
- [x] `run_auto_entry_check` returns `SKIPPED_ALREADY_OPEN` when a
      position already exists for the symbol, `SKIPPED_NO_SIGNAL` when
      the signal is `False`, and `SKIPPED_INSUFFICIENT_FUNDS` when
      `non_marginable_buying_power` is below the notional — each
      unit-tested independently with mocks, and each confirmed to make
      no order-placement call.
- [x] `run_auto_entry_check` calls `open_protected_position` with
      `tier="moderate"` and returns `ENTERED` when a position isn't
      already open, the signal is `True`, and funds are sufficient —
      unit-tested with a mocked `open_protected_position`.
- [x] `run_auto_entry_check` returns `ORDER_NOT_FILLED` (not a raised
      exception) when `open_protected_position` raises `TradingError`.
- [x] `run_auto_entry_cycle` calls `run_auto_entry_check` once per
      symbol in `AUTO_ENTRY_SYMBOLS` (all 6) and returns all results —
      unit-tested with a mocked `run_auto_entry_check`.
- [x] `run_cycle.py` skips the auto-entry step entirely (no API calls)
      when `settings.auto_entry_enabled` is `False` — unit-tested, and
      confirmed live (2026-07-11): `python -m crypto_bot.run_cycle`
      against the real paper account with `AUTO_ENTRY_ENABLED=false`
      ran only the reconciliation check.
- [x] `_crypto_buying_power` reads `non_marginable_buying_power`, not
      `buying_power` or `cash` — unit-tested against a mocked account
      object with different values for all three fields, confirming the
      right one is used.
- [x] Live verification (2026-07-11): `get_recent_closes` confirmed
      returning real 5-minute bar data with the trailing partial bar
      correctly excluded across all 6 symbols (PAXG/USD returned only 7
      complete closes due to thin trading activity — a real data-gap
      case, correctly handled by `check_entry_signal`'s "fewer than 20 ->
      False" fallback, not a bug). `run_auto_entry_check` against the
      real paper account confirmed both `SKIPPED_NO_SIGNAL` (UNI/USD)
      and `SKIPPED_ALREADY_OPEN` (XRP/USD, after the entry below).
      **The "enters and places an order" path was also verified live**,
      not just by unit test as originally expected — a real 5/20
      crossover happened on XRP/USD between two verification calls
      moments apart, so `run_auto_entry_check` went all the way through:
      opened a real paper position (~8.76 XRP/USD @ $1.1151) with its
      stop-loss attached and tracked (`exit_state.json` confirmed target
      price `1.152215079`, tier `moderate`) — unlike prior features'
      live verification, the account was not necessarily returned to a
      clean/flat state afterward; see conversation for the final
      disposition of this position.
- [x] README section documenting the 6 auto-entry symbols, the signal,
      the `AUTO_ENTRY_ENABLED`/`AUTO_ENTRY_NOTIONAL` env vars, and the
      live buying-power gate (in plain terms: real spendable cash
      checked fresh before every attempt, not a running counter).
- [x] (2026-07-11, ADR 0006) `run_auto_entry_check` returns
      `SKIPPED_TOTAL_CAP_REACHED` when `total_spent + notional` would
      exceed `AUTO_ENTRY_TOTAL_CAP` (and is skipped entirely, no check
      at all, when the cap is `0`) — unit-tested, confirmed no signal/
      buying-power/order calls happen when capped.
- [x] `run_auto_entry_check` returns `SKIPPED_DAILY_CAP_REACHED` the same
      way for `AUTO_ENTRY_DAILY_CAP`, and the daily counter resets when
      the tracked date differs from the current UTC date — unit-tested
      with a state fixture dated "yesterday" (`effective_daily_spent`
      and `record_spend` also unit-tested directly in
      `tests/test_auto_entry_spend.py`).
- [x] A successful `ENTERED` result increments both `total_spent` and
      `daily_spent` by the notional amount in `auto_entry_spend_state.json`;
      a skip or `ORDER_NOT_FILLED` result does not — unit-tested.
- [x] `auto_entry_spend_state.json` added to `.gitignore`.
- [x] Live verification (2026-07-11): a deliberately tiny total cap
      (`$1`) against the real paper account correctly returned
      `SKIPPED_TOTAL_CAP_REACHED` (`total_spent=$0 cap=$1`); a
      deliberately tiny daily cap likewise returned
      `SKIPPED_DAILY_CAP_REACHED` (`daily_spent=$0 cap=$1`). Confirmed
      `auto_entry_spend_state.json` was not created by either skip-only
      call — only a real `ENTERED` fill writes state.
- [x] README updated with the two new env vars and what "total" (never
      auto-resets) vs. "daily" (UTC-day rollover) mean in plain terms.

## Open Questions

None — all resolved with the user before drafting (2026-07-11):

- Symbol list: top 5 by live 24h Alpaca dollar volume (BTC/USD,
  ETH/USD, AAVE/USD, UNI/USD, PAXG/USD), excluding stablecoin-pegged
  pairs, DOGE, and XRP from the ranking-driven picks — plus XRP/USD
  added on top at the user's explicit request (personal holdings/
  interest, not a volume-ranked pick). 6 symbols total, fixed.
- Per-trade notional: `AUTO_ENTRY_NOTIONAL` env var, code default `$10`
  (Alpaca's minimum, used only if unset) — the user's actual `.env` for
  paper trading is `$100` (updated 2026-07-11), applied per symbol.
- Spending gate: live `non_marginable_buying_power` check per attempt,
  no locally-persisted budget/counter — required by this project's
  existing "no preset dollar ceiling" constraint, and consistent with
  the corrected design the OANDA sibling project converged on after
  initially shipping (then removing) a notional budget-cap counter.
- Enable gate: `AUTO_ENTRY_ENABLED`, default off — an explicit switch
  required before this feature does anything, on top of (not instead
  of) the existing paper/live-trading gate.
- Signal timeframe: 5-minute bars, 5/20-period SMA crossover, checked
  every 2-minute cron cycle (feature 7's existing cadence) —
  intentionally more responsive than the hourly-bar option, to actually
  make use of that tight cadence for entries, not just exits.

**Update (2026-07-11), resolved with the user, see ADR 0006:** optional
total ($1000 default) and daily ($200 default) spending caps added on
top of the live buying-power check, scoped to auto-entry only. Both
controlled by a single env var each (`0` = off, `>0` = on at that
amount) — no separate enable/disable flag. Explicitly no reset/increase
command surface in this feature (the user's call, unlike the OANDA
sibling project's now-removed `/reset_budget`/`/increase_budget`) — the
total cap in particular has no way to reset itself once reached short of
manual intervention.

## Out of Scope / Future Work

- Alternative/multiple entry signals (RSI, breakout, etc.).
- Backtesting the strategy against historical data before going live
  with it.
- Making `AUTO_ENTRY_SYMBOLS` configurable via `.env` instead of a
  hardcoded constant, if the symbol list needs to change often enough
  to warrant it.
- Per-symbol notional overrides.
- ~~An optional secondary/aggregate spending cap~~ Done, see the
  2026-07-11 Update above and ADR 0006.
- A reset/raise command for the total or daily cap (e.g. via Telegram,
  feature 10) — explicitly not built here; today the only way to lift
  either cap is editing `.env`/the state file by hand.
- Telegram notifications on auto-entry actions, including whether either
  new `SKIPPED_*_CAP_REACHED` result deserves a proactive alert — feature
  10 (see ADR 0006's Consequences).
