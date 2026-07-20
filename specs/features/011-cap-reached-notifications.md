# Feature: Auto-entry cap-reached notifications

Status: Done
Depends on: [009-auto-entry-strategy](009-auto-entry-strategy.md), [010-telegram-bot](010-telegram-bot.md)
Related ADRs: [0006-optional-auto-entry-spending-caps](../adr/0006-optional-auto-entry-spending-caps.md)

## Summary

Send a single Telegram notification the first time either of feature 9's
optional spending caps (ADR 0006: `AUTO_ENTRY_TOTAL_CAP`,
`AUTO_ENTRY_DAILY_CAP`) actually blocks an entry — not on every cycle
after that. This closes the open follow-up ADR 0006 already flagged in
its Consequences section: `SKIPPED_TOTAL_CAP_REACHED` and
`SKIPPED_DAILY_CAP_REACHED` are currently silent (`run_cycle.py`'s
`_ENTRY_MESSAGES` only announces `ENTERED` and
`SKIPPED_INSUFFICIENT_FUNDS`), so a cap being hit is currently
indistinguishable from the bot being broken — this surfaced directly
2026-07-20, when the total cap had been silently blocking every entry
for 5 days with zero signal to the user.

## Goals

- Notify once, the first time `SKIPPED_TOTAL_CAP_REACHED` occurs after
  the cap was not-yet-reached.
- Same for `SKIPPED_DAILY_CAP_REACHED`, independently (the two caps are
  unrelated and both already independent in ADR 0006).
- Re-arm automatically: if the cap stops being the blocking reason (cap
  raised in `.env` past current spend, cap disabled via `0`, or the
  daily cap's natural UTC-midnight rollover) and is later reached again,
  notify again. "First time" means first time *per capped episode*, not
  a lifetime-once flag.

## Non-Goals

- No in-app reset/raise command for either cap — ADR 0006 already
  decided against building that command surface, and this feature
  doesn't revisit that decision.
- No notification for the routine, expected skip reasons
  (`SKIPPED_ALREADY_OPEN`, `SKIPPED_NO_SIGNAL`) — unchanged from
  feature 10's existing scope, these fire too often across 6 symbols
  every 2 minutes to be useful.
- No change to cap semantics themselves (values, the `0`-disables
  convention, total-cap-never-auto-resets) — this feature only adds
  visibility, it doesn't change when or whether a cap blocks a trade.

## Requirements

1. `auto_entry_spend_state.json` (`crypto_bot/auto_entry_spend.py`)
   gains two new persisted booleans: `total_cap_notified`,
   `daily_cap_notified` (both default `False` for state files that
   predate this field, same pattern as `SpendState`'s existing fields).
2. On each auto-entry check per symbol, immediately before the existing
   total-cap comparison: if the check newly evaluates to "capped" and
   `total_cap_notified` is `False`, this cycle's result carries a
   notify-worthy flag and the state is saved with
   `total_cap_notified=True`. If the check evaluates to "not capped",
   `total_cap_notified` is reset to `False` (whatever its previous
   value) so a future capping notifies again. Same logic, independently,
   for `daily_cap_notified` against the daily-cap comparison.
3. `run_cycle.py`'s notification dispatch is extended so a first-time
   cap-reached result sends a Telegram message, worded distinctly from
   `SKIPPED_INSUFFICIENT_FUNDS` (a cap is a self-imposed limit, not a
   funds shortage — the message should make that distinction obvious,
   e.g. surfacing which cap, its dollar value, and that auto-entry is
   now blocked until it's raised/disabled/resets).
4. All dollar amounts in the new message (and, per this feature's
   bundled scope, existing Telegram messages generally) are formatted
   with thousands separators — see Requirement 5.
5. **Bundled with this spec at the user's request:** add thousands-place
   comma formatting to dollar figures across existing Telegram message
   text (entry fills, exit fills, skip/cap details, `/positions`,
   buying-power figures, etc.) — a formatting fix, not a behavior
   change, riding along with this feature since it touches the same
   notification strings.

## Design / Approach

Two boolean flags on `SpendState`, updated as a side effect of the
existing cap comparisons in `run_auto_entry_check` (`crypto_bot/
strategy.py`) — no new state file, no new module. The "reset to False
when not-capped, notify-and-set-True on the not-capped-to-capped
transition" rule means the flags always reflect "have we already told
the user about *this* capped episode," self-correcting across `.env`
edits, manual state edits, or the daily rollover without any special-
cased reset path.

`AutoEntryResult` needs a way to carry "this skip is notify-worthy" back
to `run_cycle.py` without overloading the `action` Literal (which tests
and other call sites already match on) — likely an additional field
(e.g. `notify: bool = False`) rather than new action variants, but this
is an implementation detail to confirm at build time, not a spec
decision.

For Requirement 5 (comma formatting): Python's `f"{amount:,.2f}"` (or
equivalent for `Decimal`) applied at each message-construction site.
Scope is Telegram-facing text only, per the user's request — log lines
(`logger.info(...)`) are left as-is unless that turns out to be
inconsistent/awkward in practice.

## Environment Variables / Config

None new — reuses `AUTO_ENTRY_TOTAL_CAP` / `AUTO_ENTRY_DAILY_CAP` from
feature 9 / ADR 0006 as-is.

## Acceptance Criteria

- With `AUTO_ENTRY_TOTAL_CAP` set low enough to be reachable in a test
  run, the first cycle that hits it sends exactly one Telegram message
  naming the total cap and its dollar value, formatted with commas.
- Subsequent cycles while still capped send no further message.
- Raising the cap (or resetting spend) past current spend, then hitting
  it again, sends a new notification.
- Same three behaviors verified independently for the daily cap,
  including that its natural UTC-midnight reset re-arms notification
  without any manual intervention.
- Existing Telegram messages with dollar amounts (entry/exit fills,
  `/positions`, buying-power figures) now show thousands separators.
- All existing tests still pass; new tests cover the notify-once/re-arm
  transition logic for both caps.

## Open Questions

- Exact wording for the cap-reached message.
- Whether `daily_cap_notified` should also reset (in addition to the
  transition-based reset) explicitly on the UTC daily rollover, or
  whether the transition rule already covers it correctly in all cases
  (worth confirming with a test that spans a rollover while still
  capped both days).

## Out of Scope / Future Work

- An in-app reset/raise command remains explicitly out of scope per ADR
  0006 unless the user revisits that decision separately.
