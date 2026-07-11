# Feature: Manual close, and a safe combined open-and-protect action

Status: Done
Depends on: [004-place-market-order](004-place-market-order.md), [005-monitor-open-positions](005-monitor-open-positions.md), [006-stop-loss-take-profit](006-stop-loss-take-profit.md)
Related ADRs: [0004-manual-stop-loss-take-profit-for-crypto](../adr/0004-manual-stop-loss-take-profit-for-crypto.md), [0005-single-live-exit-order-per-position](../adr/0005-single-live-exit-order-per-position.md)

## Summary

Two gaps found while wiring features 4–6 together manually after
feature 6 shipped:

1. **No way to close a position on demand.** Spec 006 explicitly left
   this as a Non-Goal. Confirmed live (2026-07-10) what actually happens
   if you try anyway (e.g. via Alpaca's dashboard) while a stop-loss
   order is attached: it doesn't silently orphan the order, it just
   **fails outright** (`"insufficient balance"`, same lockup mechanic as
   ADR 0005) — you'd have to know to cancel the stop-loss order yourself
   first, then close.
2. **A real bug in how `attach_protective_orders` would get called in
   practice.** Confirmed live: `OrderResult.filled_qty` (from placing
   the entry order) doesn't equal the position's actual quantity —
   Alpaca deducts its crypto trading fee from the asset itself, so
   `filled_qty` overstates real holdings by roughly the fee percentage
   (observed: `0.000152726` reported vs. `0.000152344` actually held, a
   ~0.25% gap). Sizing a stop-loss order off `filled_qty` directly fails
   with the same "insufficient balance" error, even on a fresh,
   successful trade.

## Goals

- `crypto_bot.exits.close_position(client, symbol) -> CloseResult`:
  cancels any tracked stop-loss order first, then closes the position,
  polling for a terminal fill status.
- `crypto_bot.trading.open_protected_position(client, data_client,
  symbol, notional, tier) -> OpenedPosition`: places the entry order,
  fetches the position's *real* quantity, then attaches the stop-loss —
  the correct, safe way to combine features 4 and 6, replacing ad hoc
  wiring at each call site.

## Non-Goals

- No Telegram/command-line interface exposing these — still not
  decided/built (see backlog notes on notifications).
- No change to the reconciliation check (feature 7) — it already
  handles a stop-loss order that disappears out from under it (e.g.
  because `close_position` canceled it) via its existing
  canceled/expired/rejected cleanup branch.

## Requirements

1. `crypto_bot/orders.py`'s polling loop extracted into a reusable
   `poll_until_terminal(client, order_id, symbol)`, used by both
   `place_market_order` and `close_position`.
2. `close_position` accepts the slash symbol form (`BTC/USD`, matching
   order/exit_state convention), looks up `exit_state` for a tracked
   stop-loss order, cancels it if present via `cancel_order_by_id`, then
   calls Alpaca's `close_position` with the no-slash form (`BTCUSD`,
   confirmed live this is what that endpoint expects).
3. `open_protected_position` is buy-only (Alpaca crypto is spot-only, no
   short selling, so there's no "open a protected short" case) and
   raises `TradingError` if the entry order doesn't fill, or if no
   matching position is found afterward — both before ever calling
   `attach_protective_orders`.
4. On `alpaca.common.exceptions.APIError`, wrap it in `ExitError`
   (`close_position`) or let underlying wrapped errors propagate
   (`open_protected_position` re-raises as `TradingError` around
   `PositionError` from the position lookup); never leak the API
   key/secret.

## Design / Approach

Implemented in `crypto_bot/exits.py` (`close_position`, reusing
`crypto_bot.orders.poll_until_terminal`) and new module
`crypto_bot/trading.py` (`open_protected_position`, `OpenedPosition`,
`TradingError`). See those files for the exact implementation.

## Environment Variables / Config

None new.

## Acceptance Criteria

- [x] `close_position` cancels a tracked stop-loss order before closing
      (mocked); works fine when there's no tracked order (mocked);
      `APIError` from either the cancel or the close step wrapped in
      `ExitError` without leaking credentials (mocked).
- [x] `open_protected_position` calls `attach_protective_orders` with
      the position's real quantity, not the order's `filled_qty`
      (mocked, explicitly asserts the two differ); raises before
      attaching if the order didn't fill or no position was found;
      matches the position by the no-slash symbol form.
- [x] 12 new unit tests (5 for `open_protected_position`, 7 for
      `close_position`), all mocked, no network. 56/56 project tests
      passing.
- [x] Verified live end-to-end against the real paper account:
      `open_protected_position` placed a $10 BTC/USD buy and attached a
      stop-loss without the insufficient-balance error the naive
      (buggy) version hit; `close_position` then canceled that
      stop-loss and closed the position cleanly. Account left with no
      open positions, orders, or `exit_state.json` entries afterward.

## Open Questions

None.

## Out of Scope / Future Work

- Exposing either function via a command interface (Telegram or
  otherwise) — not scoped yet.
