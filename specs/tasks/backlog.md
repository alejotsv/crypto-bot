# Feature backlog

Tracks the status of each feature spec. Update this file whenever a spec
is created, approved, or implemented. Status values: `Not started`,
`Draft`, `Approved`, `In Progress`, `Done`.

| # | Feature | Spec | Status |
|---|---------|------|--------|
| 1 | Project structure and dependencies | `specs/features/001-project-structure-and-dependencies.md` | Done |
| 2 | Alpaca API authentication (paper) | `specs/features/002-alpaca-authentication.md` | Done |
| 3 | Fetch live price data (a crypto pair) | `specs/features/003-fetch-live-price-data.md` | Done |
| 4 | Place a basic market order (buy/sell) | `specs/features/004-place-market-order.md` | Done |
| 5 | Monitor open positions | `specs/features/005-monitor-open-positions.md` | Done |
| 6 | Stop-loss/take-profit (single live Stop Limit order, tracked take-profit target) | `specs/features/006-stop-loss-take-profit.md` | Done |
| 7 | Scheduled monitoring (cron, every 2 minutes) | `specs/features/007-scheduled-monitoring.md` | Done (code/docs; actual Pi deployment is the user's manual step) |
| 8 | Manual close, and a safe combined open-and-protect action | `specs/features/008-manual-close-and-safe-open.md` | Done |
| 9 | Automated entry strategy | `specs/features/009-auto-entry-strategy.md` | Done |
| 10 | Telegram two-way bot (commands + notifications) | `specs/features/010-telegram-bot.md` | Done |

## Notes

- **2026-07-13, feature 9's entry signal replaced (ADR 0007):** the
  original 5/20 SMA crossover backtested below breakeven (28.3% win
  rate vs. 33.3% needed); an ad-hoc "regime filter + pullback" fix
  looked promising but failed out-of-sample. Broadened to test 9
  established, documented entry strategies (Donchian breakout,
  ADX-filtered trend, RSI(2) mean-reversion, MACD, Bollinger squeeze
  breakout, VWAP reversion, opening-range breakout) across 3
  non-overlapping 90-day windows — **none reliably beat breakeven across
  all 3**. Switched to Bollinger squeeze breakout as the best-performing
  candidate found (35.1% average win rate), with an explicit caveat: it
  still fell short of breakeven (28.4%) in the one adverse window that
  broke every strategy tested. See ADR 0007 for full rationale;
  `crypto_bot/strategy.py` and `tests/test_strategy.py` updated
  accordingly, all 131 tests pass.
- **Open follow-up, not yet investigated:** every one of the 9 entry
  strategies tested for the above — trend-following and mean-reversion
  alike — failed specifically in the same historical window
  (2026-01-14 to 2026-04-14). Worth understanding what characterized
  that period (e.g. realized volatility, a broad market-wide drawdown,
  low trend persistence generally) to see whether a regime-detection
  filter (sit out clearly adverse conditions rather than trade through
  them with any entry rule) is a more promising direction than another
  entry signal. Full backtest methodology and per-strategy results are
  in `LOCAL_NOTES.md` (gitignored, local machine only).
- **2026-07-12, feature 10 (Telegram bot) marked Done:** the last open
  acceptance criterion (live verification) was blocked on real
  `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`/`DEFAULT_ORDER_NOTIONAL` values,
  which are now set in `.env`. User confirmed live: `/positions` and
  `/buy BTC 100` both worked from Telegram, and `send_message`
  notifications were received for two real auto-entry trades after
  `AUTO_ENTRY_ENABLED` was flipped to `true` (previously `false`, which
  is why the bot hadn't auto-entered in its first 9 hours running).
  All 10 backlog features now Done.
- **2026-07-11, feature 9 amended post-implementation (ADR 0006):**
  optional total ($1000 default) / daily ($200 default) spending caps
  added on top of the live buying-power check, at the user's explicit
  request, scoped to auto-entry only. Each cap is one env var that's
  both the on/off switch and the limit (`0` = off). This is a
  deliberate, scoped exception to `constraints.md`'s "no preset dollar
  ceiling" rule — recorded there and in ADR 0006, not silently added.
  New state file `auto_entry_spend_state.json` (gitignored) tracks
  cumulative spend; `crypto_bot/auto_entry_spend.py` is the new module.
  89/89 tests passing; live-verified with deliberately tiny caps
  (`$1`) rather than waiting for real spend to accumulate.
- **2026-07-11, feature 9 (auto-entry) drafted, deliberately placed
  ahead of the Telegram bot:** the user considers auto-entry and
  auto-exit "the two main features" of this bot, so auto-entry had to
  exist before Telegram wraps notifications/commands around it — the
  Telegram spec (originally drafted as feature 9) was renumbered to 10
  and updated to depend on and notify for feature 9's actions. Along the
  way, verified live via `get_all_assets` that Alpaca actually supports
  73 tradable crypto pairs, not the "~20 majors" the specs previously
  claimed (see `platform-decision.md`'s 2026-07-11 correction) — do not
  cite ~20 anywhere else in this repo, it's stale.
  - Symbol list resolved with the user: top 5 by live 24h Alpaca dollar
    volume (BTC/USD, ETH/USD, AAVE/USD, UNI/USD, PAXG/USD), excluding
    stablecoin-pegged pairs, DOGE (user's call: low quality), and XRP
    (excluded from the volume ranking, but then added back on top at
    the user's explicit request — personal holdings/interest, not a
    volume-driven pick). 6 symbols total, fixed constant, not
    `.env`-configurable for v1.
  - Spending gate resolved: this project's existing "no preset dollar
    ceiling" constraint (`specs/context/constraints.md`) rules out a
    locally-tracked budget counter like the OANDA sibling project
    originally shipped (and later removed, see that project's spec
    012) — feature 9 goes straight to a live
    `non_marginable_buying_power` check per attempt, no counter to add
    or reset.
  - Per-trade notional: `AUTO_ENTRY_NOTIONAL` env var, code default $10
    (Alpaca's crypto minimum, fallback only), applied per symbol per
    triggered entry. **Update (2026-07-11):** the user's actual `.env`
    value for paper trading is $100, not the $10 default — recorded per
    the "no preset dollar ceiling" constraint (a specific figure from
    conversation is the user's expected usage, not a code default to
    change).
  - Enable gate: `AUTO_ENTRY_ENABLED`, default off — a second explicit
    switch on top of (not replacing) the existing paper/live-trading
    gate, so shipping this feature doesn't silently start unattended
    spending on the Pi.
  - Signal: 5-minute bars, 5/20-period SMA crossover, checked every
    2-minute cron cycle — chosen over reusing feature 6's hourly ATR
    bars specifically so the signal is responsive enough to make use of
    that tight cadence.
- **2026-07-11, feature 10 (Telegram, originally drafted as feature 9)
  updated:** now depends on feature 9 and notifies on its actions too
  (`ENTERED`/`SKIPPED_INSUFFICIENT_FUNDS`, not the routine
  `SKIPPED_ALREADY_OPEN`/`SKIPPED_NO_SIGNAL` results — those would fire
  too often across 6 symbols every 2 minutes to be useful). Otherwise
  unchanged from its original scope: `/buy`'s amount defaults to a new
  `DEFAULT_ORDER_NOTIONAL` env var when omitted (always overridable
  inline, not an enforced ceiling — see the spec's Non-Goals); a
  persistent button keyboard (Buy default-symbol/-amount, Positions) is
  in scope; no `/balance` command for v1.

- This list is deliberately short — only what's obviously needed to get
  a working end-to-end loop. Anything past position monitoring
  (notifications, automated entry signal, risk tiers, etc.) hasn't been
  scoped in conversation yet; add rows here once it has, don't
  pre-populate them by guessing.
- **Known future feature, deliberately last, not yet scoped:** an
  optional natural-language command path (via Alpaca's MCP server)
  alongside whatever preset Telegram buttons/typed commands get built —
  additive, not a replacement. Automated entry/exit decisions stay
  rule-based regardless; this is only about how a *human* manually
  triggers a trade. Requires its own ADR (a deliberate, scoped exception
  to "rule-based first, no LLM") when it's actually time to build it —
  see `specs/context/constraints.md`.
- (2026-07-10: the first six backlog specs were drafted upfront at the
  user's explicit request, ahead of the earlier "draft only when it's
  time" convention — that convention no longer reflects actual practice
  in this project. Feature 7 was added the same day once feature 6's
  open questions surfaced the need for it.)
- Feature 6 (stop-loss/take-profit) is deliberately positioned as a
  first-class early feature, not a later refinement — see
  `specs/context/constraints.md` for why (a poll-based recompute design
  lets the effective stop-loss drift, and enforcement is only as fast as
  the poll interval).
- **Correction (2026-07-10):** feature 6 was originally planned around
  Alpaca native bracket orders. Verified against Alpaca's own docs that
  bracket/OCO orders aren't supported for crypto at all — see ADR 0004.
  Actual design: a Limit order for take-profit, a Stop Limit order for
  stop-loss (`stop_price` set above the true floor `limit_price` by a
  buffer), plus this project's own logic for OCO (cancel the other leg
  on a fill) and a backstop that force-market-sells if the stop-loss
  order fails to fill despite price crossing its trigger.
- **2026-07-10, feature 6's open questions resolved:** risk tiers
  confirmed wanted (conservative/moderate/aggressive, multipliers
  carried over directly from the OANDA project's table) — see feature
  6's Requirement 2. Reconciliation cadence confirmed at every 2
  minutes (tighter than the OANDA project's 5, justified by crypto's
  higher volatility), on the same Raspberry Pi already running the
  OANDA sibling project — new feature 7 added to the backlog to
  schedule it.
- **Second correction (2026-07-10), found during implementation:** the
  "attach both a take-profit Limit order and stop-loss Stop Limit order"
  design (from the first correction above) also doesn't work — confirmed
  live that submitting the first sell order locks the *entire* position
  balance, so a second full-quantity sell order for the same position is
  rejected as insufficient balance. See ADR 0005: only the stop-loss is
  ever a live order; take-profit is a tracked target realized by the
  reconciliation check.
- **2026-07-10, feature 8 added same day:** while manually wiring
  features 4–6 together to verify feature 6 live, found (a) no way to
  close a position on demand existed (spec 006 left it as a Non-Goal),
  and (b) a real bug — `OrderResult.filled_qty` differs from the
  position's actual quantity (Alpaca deducts its crypto fee from the
  asset itself), so sizing a stop-loss off `filled_qty` directly fails.
  Both fixed: `crypto_bot.exits.close_position` (cancels any tracked
  stop-loss first, since Alpaca refuses to close a position while one
  holds its balance) and `crypto_bot.trading.open_protected_position`
  (fetches the real position quantity before attaching protection).
  All 8 backlog features now Done (feature 7's Pi deployment excepted —
  manual step). 56/56 tests passing, verified live against the real
  paper account, account left clean.
