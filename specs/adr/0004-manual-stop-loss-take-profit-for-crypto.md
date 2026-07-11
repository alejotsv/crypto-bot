# ADR 0004: Manual stop-loss/take-profit (no bracket orders) for crypto

Status: Accepted
Supersedes: the "native bracket-order support" assumption in ADR 0002
and `CLAUDE.md`'s original stop-loss/take-profit constraint.

## Context

ADR 0002 and the project's original constraints assumed Alpaca's native
bracket orders (entry + attached stop-loss + take-profit in one call)
would work for crypto the same way they do for Alpaca equities — this
was a real factor in choosing Alpaca as the platform. Verified directly
against Alpaca's own support documentation (2026-07-10): **bracket
orders and OCO orders are not supported for crypto at all** — only
Market, Limit, and Stop Limit orders are. This assumption was wrong and
needs correcting before feature 6 (stop-loss/take-profit) is specced.

Alpaca crypto does still support the underlying pieces separately:

- A **Limit order** (sell above current price) works for take-profit —
  it only ever executes at its limit price or better, so no gap risk on
  this side.
- A **Stop Limit order** (stop price = trigger, limit price = execution
  floor) works for stop-loss, but has a real failure mode: if price
  drops fast enough to blow through both the stop price and the limit
  price in one move (a flash crash — not rare in crypto), the order can
  fail to fill entirely, leaving the position completely unprotected at
  exactly the moment protection was needed most.

What's missing is **OCO** — Alpaca won't automatically cancel the
take-profit leg when the stop-loss fills, or vice versa. That has to be
handled by this project's own logic.

## Decision

Stop-loss and take-profit are each placed as separate, independent
orders (not a single bracket call):

- **Take-profit**: a Limit sell order at the ATR-derived target price.
- **Stop-loss**: a Stop Limit sell order, where:
  - `limit_price` = the actual worst acceptable sale price (the
    ATR-derived stop level) — a limit order's own guarantee means this
    is never violated; the order simply won't execute below it.
  - `stop_price` = set *above* `limit_price` by a deliberate buffer, so
    the order has room to actually execute before the market falls all
    the way to the hard floor. The size of that buffer is a feature 6
    design detail (likely also ATR-based, to stay consistent with how
    every other distance in this project scales with volatility) — not
    fixed here.

Because Alpaca provides no OCO linkage, this project adds its own
backstop, reusing the same cron-style check pattern already used
elsewhere: periodically confirm whether the stop-loss order has failed
to fill despite price having crossed its trigger, and if so, cancel it
and submit a plain **market** sell instead — guaranteeing an eventual
exit, at the cost of an unpredictable fill price in that scenario. The
same backstop also needs to cancel the *other* leg once either order
fills (the OCO behavior Alpaca doesn't provide for free).

## Consequences

- More moving parts than a single bracket-order call: two independent
  orders to track, plus a periodic check to enforce OCO-like behavior
  and catch a stop-limit that failed to fill.
- Unlike the sibling forex project's final design (ADR 0006 there,
  native OANDA bracket orders), this project's exit enforcement is not
  fully broker-side and instant — there's a real (if narrow) window
  where a fast crash blows through the stop-limit and the backstop
  hasn't run yet.
- `CLAUDE.md` and `specs/context/constraints.md`'s stop-loss/take-profit
  constraint need updating to describe this design instead of the
  now-incorrect "native bracket order" language.
- `specs/context/platform-decision.md`'s claim that Alpaca offers
  "native bracket orders ... closest match" was based on this same wrong
  assumption — needs a correction note, not a rewrite (the rest of the
  platform comparison — liquidity, legal availability, library quality
  — still holds; only the bracket-order point was wrong, and it wasn't
  the deciding factor on its own).
