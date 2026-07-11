---
title: Hard constraints
---

# Hard constraints

These apply to every spec and every line of code in this project. If a
request conflicts with one of these, flag it and confirm with the user
before proceeding rather than silently overriding it.

## Account safety

- Target Alpaca's **paper trading** environment only.
- Never target Alpaca's live-trading environment or place a real-money
  order unless the user has explicitly said to move to live trading in
  the current conversation.
- No preset dollar ceiling is baked into order-sizing logic. Spending is
  bounded only by: (a) an explicit manual gate the user controls, and
  (b) a live check against real account funds (buying power/cash
  available) at the moment of each trade. A specific dollar figure
  mentioned in conversation is the user's own expected usage, not a
  number to hardcode or design a cap around.
  - **Scoped exception (ADR 0006, 2026-07-11):** feature 9's auto-entry
    has optional total/daily spending caps, explicitly requested by the
    user, on top of (not instead of) the live funds check above.
    Disabled per-cap via `0`, scoped to auto-entry only — never applies
    to manual trades. Don't generalize this exception elsewhere without
    the same kind of explicit request; the default posture everywhere
    else in this project is still no preset ceiling.

## Secrets handling

- All credentials (Alpaca API key/secret, and any notification-service
  credentials) are supplied via environment variables, loaded through
  `python-dotenv` from a local `.env` file.
- `.env` is gitignored and never committed. `.env.example` documents
  required variable names with placeholder values only.
- Never log, print, or echo credential values, even at debug log level.
- Never hardcode credentials in source, tests, or specs.

## Language/library choices

- Python only.
- Alpaca access goes through `alpaca-py`. Switching libraries requires an
  ADR.
- Trading logic is rule-based (explicit, deterministic conditions). No
  LLM or ML-based decision-making until the user explicitly requests
  that phase.
- Stop-loss/take-profit prices are computed once, at order-placement
  time, never re-evaluated against a fixed entry price on a recurring
  poll loop (recomputing the stop distance on every check while
  anchoring it to a fixed entry price lets the effective stop-loss
  drift, loosening exactly when a trade is moving against you and
  volatility rises).
- Alpaca does not support bracket/OCO orders for crypto (Market, Limit,
  and Stop Limit only — verified against Alpaca's own docs), and doesn't
  even allow two independent full-quantity sell orders on the same
  position at once (confirmed live — the first locks the entire
  balance). Per ADR 0004/0005: only the stop-loss is ever a live order
  (a Stop Limit order with `stop_price` set above the true floor
  `limit_price` by a deliberate buffer, since a Stop Limit order can
  fail to fill entirely if price gaps through both in a fast move);
  take-profit is a tracked target, realized by canceling the stop-loss
  and submitting a market sell once the reconciliation check sees price
  reach it. The same check backstops the stop-loss if it's stuck
  unfilled past its trigger.

## Scope discipline

- This is a learning project. Prefer simple, readable implementations
  over production hardening (no distributed job queues, no elaborate
  retry/circuit breaker frameworks, no premature abstraction for
  multi-pair/multi-strategy support) unless the user asks for it.
- Build features in the order defined in `specs/tasks/backlog.md` — don't
  jump ahead to order placement before authentication and market data
  are specced and working, for example.
