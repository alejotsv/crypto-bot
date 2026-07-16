# ADR 0007: Replace the 5/20 SMA crossover with a Bollinger squeeze breakout entry signal

Status: Accepted
Supersedes: feature 9's original entry signal (5/20-period SMA crossover
on 5-minute bars). Does not change feature 6/9's exit mechanism (ATR-
based stop-loss/take-profit, moderate tier) or any of the gating logic
around it (position-already-open check, spending caps, live buying-power
check) — only the "when do we buy" signal itself.

## Context

After ~9 hours live with `AUTO_ENTRY_ENABLED=true`, the user noticed all
3 auto-entered positions sitting at a small unrealized loss and suspected
the 5/20 SMA crossover — a lagging trend signal — tends to buy near the
top of the swing that triggered it. Rather than guess from 3 open
trades, this was investigated with real historical data (Alpaca's own
5-minute/hourly bars), reusing the actual production signal and ATR-
based exit logic rather than a fresh reimplementation.

**Backtest #1 (the live rule itself, 90 days):** 28.3% win rate,
below the 33.3% breakeven win rate implied by the moderate tier's 3x
stop / 6x target ATR multipliers. The aggregate positive dollar total
was carried almost entirely by 2 of 6 symbols (UNI/USD, AAVE/USD); BTC,
ETH, XRP, PAXG were all net losers individually.

**Backtest #2 (ad-hoc fix attempt):** added a longer-trend regime filter
plus a "wait for a small pullback before buying" rule. Looked like a real
fix on the same 90-day window (34.9% win rate, above breakeven) and
survived a 20-combination parameter sensitivity grid — but **failed
completely out-of-sample** on a different, non-overlapping 90-day window
(~20-25% win rate, no better than the original rule there). Lesson taken
from this failure: a result only counts if it survives testing on
multiple non-overlapping historical windows — one good window is an
invitation to overfit, not evidence.

**Backtest #3 (proven-strategy sweep, 9 candidates total across two
rounds):** tested genuinely established, documented technical entry
strategies — Donchian Channel breakout (Turtle Trading System 1),
ADX-filtered trend continuation (Wilder), RSI(2) mean-reversion (Connors
& Alvarez), MACD crossover (Appel), Bollinger squeeze breakout (Bollinger
+ TTM Squeeze concept, Carter), VWAP reversion, and opening-range
breakout — each against all 6 `AUTO_ENTRY_SYMBOLS`, same $100 notional,
same shared ATR-based exit, across **3** non-overlapping 90-day windows
(not 2, for stronger confidence). **None of the 9 reliably beat breakeven
across all 3 windows.** All 9 specifically failed in the same historical
window (2026-01-14 to 2026-04-14), while most cleared breakeven
comfortably in the most recent window — strong evidence that window was
a genuinely adverse market regime that no entry-timing idea overcomes,
not a flaw specific to any one rule.

The two closest performers, by average win rate across all 3 windows,
were ADX-filtered crossover (31.1% average) and **Bollinger squeeze
breakout (35.1% average — above breakeven on average)**. Squeeze
breakout also had the highest single-window win rate (41.7%) and the
best worst-case window (28.4%, tied with ADX-filtered) of anything
tested. Full per-strategy detail, per-symbol tables, and methodology are
in `LOCAL_NOTES.md` (gitignored, local machine only — not part of the
committed project, but the full backtest record is preserved there for
reference).

## Decision

Replace the 5/20 SMA crossover with **Bollinger squeeze breakout** as
`crypto_bot.strategy`'s entry signal, on hourly bars:

- **Squeeze**: Bollinger Bands (20-period SMA basis, ±2 standard
  deviations) sitting fully inside the Keltner Channel (same basis,
  ±1.5× ATR(14)) — a low-volatility contraction.
- **Release**: the specific hour the squeeze turns from ON to OFF (bands
  expand back outside the Keltner Channel) — the classic
  breakout-imminent signal.
- **Direction filter**: only enter if the live price is above the
  latest basis (middle) line at the moment of release — confirms an
  upward breakout, not a downward one (this project only ever goes long;
  Alpaca crypto is spot-only).

This is an **explicitly acknowledged compromise, not a validated
winner**: it is the best-performing candidate found across 9 tested
approaches, but it did *not* clear the 33.3% breakeven win rate in the
one adverse window (28.4%, vs. 33.3% needed) that broke every other
strategy too. The user made this decision with that caveat known, given
this is a paper-trading learning project rather than one where real
capital is at stake.

**Open follow-up, explicitly tracked (not yet investigated):** why did
*every* one of the 9 strategies — trend-following and mean-reversion
alike — fail specifically in that one 90-day window
(2026-01-14 to 2026-04-14)? Understanding what characterized that period
(e.g. realized volatility, a broad market-wide drawdown, unusually low
trend persistence) could inform a future regime-detection filter to sit
out similar conditions rather than trade through them with any entry
rule. See `specs/tasks/backlog.md` for this tracked as a backlog note.

## Consequences

- `crypto_bot/strategy.py`: `get_recent_closes` (5-minute bars) is
  replaced by `get_recent_hourly_bars` (hourly bars); `check_entry_signal`
  now takes `(hourly_bars, current_price)` instead of `(closes)` and
  implements the squeeze-release check above instead of the SMA
  crossover; a new `_latest_price` helper fetches a live bid quote
  (mirroring `exits.check_and_reconcile_exits`'s existing convention) as
  the direction-filter's current price. `DEFAULT_CLOSES_COUNT`/
  `BAR_TIMEFRAME`/`BAR_DURATION` (5-minute-bar constants) are removed as
  no longer meaningful; `BB_PERIOD`, `BB_STD_MULTIPLIER`,
  `KC_ATR_PERIOD`, `KC_ATR_MULTIPLIER`, `MIN_HOURLY_BARS` replace them.
- Everything else in feature 9 is unchanged: the 6-symbol list, the
  already-open check, both spending caps, the live buying-power check,
  the moderate-tier ATR-based stop-loss/take-profit, and
  `run_auto_entry_cycle`'s per-cycle structure.
- Tests: `tests/test_strategy.py`'s SMA-crossover-specific tests are
  replaced with hand-verified squeeze-breakout scenarios (a flat/tight
  low-volatility series followed by a sharp breakout bar, checked against
  a manually computed Bollinger/Keltner boundary); the `run_auto_entry_check`
  gating tests (caps, already-open, insufficient funds, spend recording)
  are updated only to mock the new function names, their logic is
  unchanged. All 131 tests pass.
- No backtesting of *this exact* production implementation was performed
  post-hoc against the historical windows (the backtest used its own
  scratch reimplementation of the same formula, in `bt_common.py`'s
  `build_bollinger_squeeze_release_series` / `bt_proven_strategies_2.py`'s
  `squeeze_entry_builder`) — a live read-only sanity check (fetching real
  current bars/quotes for all 6 symbols and confirming
  `check_entry_signal` runs without error) was performed instead, per this
  project's existing "no backtesting infrastructure in the live codebase"
  Non-Goal (feature 9's Non-Goals, still true) — the backtest lives
  entirely in the gitignored, local-only scratch scripts.
