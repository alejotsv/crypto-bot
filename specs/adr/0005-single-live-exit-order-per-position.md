# ADR 0005: Only the stop-loss is a live order; take-profit is tracked, not attached

Status: Accepted
Supersedes: the "attach both a take-profit Limit order and a stop-loss
Stop Limit order simultaneously" design in ADR 0004.

## Context

ADR 0004 established that crypto stop-loss/take-profit on Alpaca has to
be built from independent orders, since bracket/OCO orders aren't
supported for crypto. The original design submitted **both** a
take-profit Limit sell order and a stop-loss Stop Limit sell order for
the full position quantity immediately after entry.

Verified live (2026-07-10) that this doesn't work: submitting the first
sell order (take-profit) locks the **entire** position quantity against
it — `qty_available` on the position dropped to `0` immediately.
Submitting the second sell order (stop-loss) for the same quantity then
failed with `"insufficient balance for BTC (requested: X, available:
0)"`. Alpaca doesn't support reserving one quantity against two
concurrent sell orders on the same position — there is no way to have
both a live take-profit and a live stop-loss order for the same shares
at the same time.

## Decision

Only the **stop-loss** (a Stop Limit sell order) is ever submitted as a
live order on Alpaca, immediately after entry. It's the safety-critical
leg, so it gets continuous, instant, exchange-side enforcement.

The **take-profit** target price is computed at the same time (same ATR
distance/tier as before) but only **persisted** in this project's own
state (`crypto_bot.exit_state`) — not submitted as an order. The
reconciliation check (feature 7's cron, `check_and_reconcile_exits`)
compares the current price against the tracked target on every run: if
price has reached it, the stop-loss order is canceled and a market sell
is submitted to realize the gain.

The same reconciliation check still backstops the stop-loss itself
(cancel + force a market sell if it's stuck unfilled past its trigger),
unchanged from ADR 0004's reasoning.

## Consequences

- Take-profit realization is now bound to the reconciliation cron's
  cadence (up to ~2 minutes late, per feature 7), not instant. This only
  affects the *upside* — the stop-loss (the safety property that
  actually matters) is unaffected and still exchange-enforced in real
  time.
- No OCO logic is needed at all anymore — there's only ever one live
  exit order per position, so there's no sibling order to cancel on a
  fill. This is simpler than ADR 0004's original design, not more
  complex, despite needing more code to track the take-profit target.
- `crypto_bot.exit_state`'s persisted schema changed from tracking two
  order IDs (take-profit + stop-loss) to tracking one order ID
  (stop-loss) plus a tracked target price.
- If price moves fast enough to blow past the take-profit target between
  cron runs, the realized sale price could differ from the exact target
  — same category of imprecision as the existing stop-loss backstop,
  not a new kind of risk.
