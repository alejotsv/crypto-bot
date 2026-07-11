# ADR 0006: Optional total/daily spending caps, scoped to auto-entry only

Status: Accepted
Supersedes: nothing outright, but is a deliberate, scoped exception to
`specs/context/constraints.md`'s "no preset dollar ceiling" rule.

## Context

`specs/context/constraints.md` has a hard rule: order sizing must never
be gated by an arbitrary hardcoded number; spending is bounded only by
(a) an explicit manual gate and (b) a live check against real account
funds at the moment of each trade. Feature 9 (automated entry strategy)
was built exactly to that rule — no locally-tracked spending counter, a
fresh `non_marginable_buying_power` check on every attempt.

The user explicitly asked (2026-07-11), after feature 9 shipped, for an
**optional** total and daily spending cap on top of that live check —
specifically for auto-entry only, not manual trades. This is a real
tension with the constraint above: a cap is, by definition, a preset
ceiling. The constraint's own text anticipates this: *"If a specific
dollar figure ever comes up in conversation, treat it as the user's own
expected usage, not a system constraint to enforce in code"* — but a cap
the user explicitly asks to have *enforced* is different from a figure
mentioned in passing. This ADR records that distinction deliberately
rather than silently overriding the constraint.

The sibling OANDA project's history is relevant precedent: it originally
shipped a similar notional budget-cap counter, then *removed* it (its
spec 012) in favor of a live `marginAvailable` check, because the
counter didn't track real money and never decreased when trades closed.
This project's caps are designed differently to avoid that exact
problem (see Decision) — they're additive on top of the live check, not
a replacement for it, and they track real dollars actually spent by
filled orders, not a notional/leveraged figure.

## Decision

Two independent, optional caps, both scoped to **auto-entry only**
(feature 9) — manual trades (a future Telegram `/buy`, or direct API
use) are never gated by either:

- **Total cap**: a lifetime cumulative ceiling on dollars spent by
  auto-entry. Never resets automatically; once reached, auto-entry stays
  blocked until the user manually intervenes (edit `.env` and/or the
  state file — no in-app reset command is part of this feature, per the
  user's explicit preference against building a reset/raise command
  surface here).
- **Daily cap**: a ceiling on dollars spent by auto-entry within a UTC
  calendar day. Resets automatically at UTC midnight — detected lazily
  (on the next auto-entry check after rollover), not via a scheduled
  job, consistent with this project's no-persistent-process design.

Both are controlled by a single env var each, where the same variable
is both the on/off switch and the limit: `0` disables the cap entirely
(skip the check), any value `> 0` enables it at that dollar amount.
Defaults (2026-07-11, user-specified): total cap `$1000`, daily cap
`$200` — both enabled out of the box once auto-entry itself is turned
on, unlike `AUTO_ENTRY_ENABLED` which defaults off.

Both caps check `attempted_spend (cumulative before this trade) +
notional > cap`, using the exact `notional` dollar amount configured for
auto-entry (not a leveraged/notional-vs-margin figure — Alpaca crypto
orders are submitted by dollar notional directly and fill at
approximately that amount, so this is already "real dollars," avoiding
the OANDA project's original mistake). Spend is only recorded after a
trade actually fills (`ENTERED`), never on a skipped or unfilled
attempt.

## Consequences

- A new small local JSON state file (`auto_entry_spend_state.json`,
  gitignored, mirroring `exit_state.py`'s existing pattern) tracks
  `total_spent`, `daily_spent`, and the UTC date `daily_spent` belongs
  to — this project's second locally-persisted state file, and a direct
  reversal of feature 9's original Non-Goal ("no locally-persisted
  spending counter/budget cap"). That Non-Goal is amended, not deleted,
  in feature 9's spec — see its 2026-07-11 Update section.
- The total cap has no automatic or in-app reset — over a long enough
  time horizon with the cap enabled, auto-entry will eventually stop
  entering anything at all unless the user raises or resets it by hand.
  This is intentional per the user's stated preference, but worth
  re-confirming if it causes confusion later (same kind of rough edge
  the OANDA project hit and documented with its original budget cap,
  though for a different underlying reason — that one didn't track real
  dollars at all, this one does but only accumulates, never a live
  balance).
- Two new `AutoEntryResult` actions (`SKIPPED_TOTAL_CAP_REACHED`,
  `SKIPPED_DAILY_CAP_REACHED`) join the existing skip reasons — feature
  10 (Telegram)'s notification list should be revisited to decide if
  either deserves a proactive alert like `SKIPPED_INSUFFICIENT_FUNDS`
  does (a cap being hit is arguably more actionable/surprising than a
  routine no-signal skip).
