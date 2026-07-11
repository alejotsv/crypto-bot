# crypto-bot

A crypto trading bot connected to Alpaca's API, built with Python. This
is a **personal learning project** — the goal is to understand
algorithmic trading mechanics (market data, order placement,
position/risk management) end to end using plain rule-based logic.

## Project status

Early spec-driven kickoff. No implementation code exists yet. Specs are
being written under `specs/` and must be reviewed/approved before code is
written against them.

## Core constraints (do not violate without explicit user instruction)

- **Paper trading account only.** All API calls target Alpaca's paper
  trading environment. Do not point the bot at Alpaca's live-trading
  environment or spend real money unless the user explicitly says to
  move to live trading.
- **No preset dollar ceiling baked into the design.** Order sizing must
  never be gated by an arbitrary number written into a spec or
  hardcoded into sizing logic. Spending is bounded only by: (a) an
  explicit manual gate — a live-trading command/flag the user turns on
  on purpose — and (b) a live check against real account funds (buying
  power/cash available via Alpaca's account API) at the moment of each
  trade. If a specific dollar figure ever comes up in conversation,
  treat it as the user's own expected usage, not a system constraint to
  enforce in code.
- **Credentials via environment variables only.** Alpaca API key/secret,
  and any notification-service credentials, must never be hardcoded,
  committed, or logged. Use `.env` (gitignored) + `python-dotenv`, with
  `.env.example` documenting required variable names (no real values).
- **Python only.**
- **Alpaca access via `alpaca-py`** (Alpaca's official SDK) — do not
  swap in a different client library without an ADR justifying the
  change.
- **Rule-based logic first.** No LLM/AI decision-making until the user
  explicitly asks for that layer. Trading logic (entries, exits, stop-
  loss/take-profit) should be deterministic and explainable.
- **Stop-loss/take-profit prices computed once, at order-placement time
  — never recomputed/re-evaluated against a fixed entry price on a
  recurring poll loop.** Recomputing the stop distance on every check
  while anchoring it to a fixed entry price lets the effective stop-loss
  drift (it can loosen exactly when a trade is moving against you and
  volatility rises) — that mistake must not be repeated here.
- **Alpaca does not support bracket/OCO orders for crypto** (verified
  directly against Alpaca's own docs — only Market, Limit, and Stop
  Limit orders are available for crypto; bracket/OCO are equities-only).
  Further confirmed live: Alpaca doesn't even allow two independent
  full-quantity sell orders on the same position at once (the first
  locks the entire balance) — see ADR 0004 and ADR 0005. Actual design:
  only the stop-loss is ever a live order (a Stop Limit order,
  `stop_price` set above the true floor `limit_price` by a deliberate
  buffer, since a Stop Limit order can fail to fill entirely if price
  gaps through both in a fast move); take-profit is a tracked target
  price, realized by canceling the stop-loss and submitting a market
  sell once the reconciliation check sees price reach it. The same
  check backstops the stop-loss itself if it's stuck unfilled past its
  trigger.
- Trading is limited to whatever pairs Alpaca's crypto offering supports
  (73 tradable pairs verified live 2026-07-11 via `get_all_assets` —
  corrected from an earlier stale "~20 majors" estimate; well beyond
  majors, e.g. also includes DOGE, SHIB, PEPE) — this is a platform
  limit, not an additional curation rule to design around. This project
  still trades majors only (e.g. BTC/USD, ETH/USD) by its own choice
  (see `specs/context/platform-decision.md`), not because Alpaca
  restricts it to that.
- This is a learning project, not a production system — favor clarity
  and correctness over robustness/scale engineering. Don't add
  production-grade concerns (retry frameworks, distributed queues, etc.)
  unless asked.

## Spec-driven development workflow

Specs live under `specs/` and are the source of truth. **Code should not
be written for a feature until a corresponding spec exists in
`specs/features/`.** If you (Claude) are asked to implement something
with no spec, write the spec first and check in with the user before
coding.

```
specs/
  context/    Background docs: project goals, non-goals, hard constraints,
              including the platform-decision writeup. Read these before
              writing any new spec.
  adr/        Architecture Decision Records. One decision per file,
              numbered sequentially (0001-, 0002-, ...). Immutable once
              accepted — superseding decisions get a new ADR that
              references the old one.
  features/   One spec per feature/capability, numbered sequentially
              (001-, 002-, ...) in the rough order they'll be built.
  tasks/      Backlog / status tracking of which feature specs exist, are
              approved, in progress, or done.
```

### Feature spec template

Every file in `specs/features/` follows this shape:

```markdown
# Feature: <Name>

Status: Draft | Approved | In Progress | Done
Depends on: <other feature specs, if any>
Related ADRs: <adr file names, if any>

## Summary
## Goals
## Non-Goals
## Requirements
## Design / Approach
## Environment Variables / Config
## Acceptance Criteria
## Open Questions
## Out of Scope / Future Work
```

### Working agreement

1. Read `specs/context/` first for background/constraints.
2. When starting a new feature, check `specs/tasks/backlog.md` and
   `specs/features/` for an existing spec before writing one.
3. Draft specs as `Status: Draft` and confirm with the user before
   flipping to `Approved` and starting implementation.
4. Record any non-obvious architectural or process decision as a new ADR
   rather than burying it in a feature spec.
5. Do not write implementation code until a feature spec is explicitly
   approved by the user.

## Planned feature order

See `specs/tasks/backlog.md` for the live list. Features 1-8
(`specs/features/001`-`008`) are all Done — feature 7's actual Pi
deployment is the one remaining manual step. Features 9-10 are Draft:

1. Project structure and dependencies
2. Alpaca API authentication (paper environment)
3. Fetching live price data (a crypto pair, e.g. BTC/USD)
4. Placing a basic market order (buy/sell)
5. Monitoring open positions
6. Stop-loss/take-profit — only the stop-loss is a live Stop Limit
   order (the safety-critical leg, exchange-enforced instantly);
   take-profit is a tracked target realized by the reconciliation check,
   ATR-based distances, conservative/moderate/aggressive risk tiers (see
   the constraint above and ADR 0004/0005 — Alpaca doesn't support
   bracket/OCO orders for crypto, and doesn't even allow two live
   full-quantity sell orders on one position at once).
7. Scheduled monitoring (cron, every 2 minutes) for feature 6's
   reconciliation check.
8. Manual close (`crypto_bot.exits.close_position`) and a safe combined
   open-and-protect action (`crypto_bot.trading.open_protected_position`,
   which fixes a real bug: an order's `filled_qty` differs from the
   position's actual quantity, since Alpaca deducts its crypto fee from
   the asset itself).
9. Automated entry strategy — 5/20-period SMA crossover on 5-minute
   bars, checked every cron cycle across a fixed 6-symbol list (BTC/USD,
   ETH/USD, AAVE/USD, UNI/USD, PAXG/USD, XRP/USD), gated by a live
   buying-power check (not a locally-tracked budget counter, per the
   "no preset dollar ceiling" constraint above) and an explicit
   `AUTO_ENTRY_ENABLED` opt-in. Deliberately placed ahead of the
   Telegram bot — the user considers auto-entry and auto-exit "the two
   main features," so auto-entry exists before Telegram wraps
   notifications/commands around it.
10. Telegram two-way bot (commands + notifications) — control surface
    for manual buy/close/positions, plus proactive alerts when features
    6 or 9 act automatically.

Anything past that is intentionally not pre-decided — scope and spec it
when it's time, same as everything else in this workflow.

## Tech stack (planned)

- Python 3.11+
- `alpaca-py` for Alpaca API access
- `python-dotenv` for environment variable loading
- `pytest` for tests
- Notification channel not yet decided — pick one when that feature is
  actually scoped, not before.
