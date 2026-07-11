# Feature: Telegram two-way bot (commands + notifications)

Status: In Progress (code/tests done; live verification pending real Telegram credentials)
Depends on: [004-place-market-order](004-place-market-order.md), [005-monitor-open-positions](005-monitor-open-positions.md), [006-stop-loss-take-profit](006-stop-loss-take-profit.md), [007-scheduled-monitoring](007-scheduled-monitoring.md), [008-manual-close-and-safe-open](008-manual-close-and-safe-open.md), [009-auto-entry-strategy](009-auto-entry-strategy.md)
Related ADRs: None

## Summary

Telegram becomes the control surface for manual trading and the alert
channel for both automatic entry and exit actions. You send it commands
(buy a symbol with stop-loss/take-profit attached, close a position,
list open positions) and it replies; it also proactively messages you
whenever the automated pieces act without a human present: feature 9's
auto-entry check opening a position (or being unable to, for lack of
funds) on any of its 6 tracked symbols, or feature 6's reconciliation
check (cron cycle, feature 7) realizing a take-profit or force-market-
selling a stuck stop-loss.

Since nothing in this project runs a persistent server, inbound
commands are picked up by **polling** Telegram's `getUpdates` once per
cron cycle (every 2 minutes, feature 7) — not a webhook, which would
need a public HTTPS endpoint this Raspberry Pi setup doesn't have. This
mirrors the sibling `trading-bot` (OANDA) project's feature
[010-telegram-bot](../../../trading-bot/specs/features/010-telegram-bot.md),
adapted for Alpaca's simpler one-position-per-symbol model (no trade
IDs), buy-only crypto (no short selling), and this project's live-
buying-power auto-entry gate instead of a locally-tracked budget counter
(so no `/reset_budget`/`/increase_budget`-style commands — see
Non-Goals).

The commands wire together `open_protected_position` and
`close_position` (feature 8) and `get_open_positions` (feature 5) —
`trading.py`'s module docstring already names a future command
interface as the intended caller of `open_protected_position`, so this
feature is the interface, not new trading logic.

## Goals

- Accept a small set of text commands from Telegram and act on them:
  buy-and-protect a symbol (entry + stop-loss attached in one action,
  per `open_protected_position`), list open positions, close a
  position.
- Also accept the same actions via a persistent reply-keyboard button
  tap, for one-tap use of the default symbol/amount/tier.
- Send a Telegram message whenever the auto-entry check (feature 9)
  opens a position automatically, or is skipped specifically for lack
  of funds (`SKIPPED_INSUFFICIENT_FUNDS` — actionable, unlike the other
  skip reasons which are routine and not notification-worthy).
- Send a Telegram message whenever the reconciliation check (feature 7)
  takes an automatic action: realizes a take-profit, or force-sells a
  stuck stop-loss.
- Only ever act on messages from the configured chat — never execute a
  command from an unrecognized `chat_id`.
- One consolidated entrypoint (`crypto_bot/run_cycle.py`, extending
  feature 7) that does, in order, per cron tick: process pending
  Telegram commands, then run the auto-entry check (feature 9, if
  enabled) and notify on any entries/insufficient-funds skips, then run
  the exit reconciliation check and notify on any action taken — so the
  crontab still only needs one line.

## Non-Goals

- No webhook / public server — polling only.
- No multi-user support — one hardcoded `chat_id` from `.env`, exactly
  like today's config pattern.
- No natural-language command parsing — fixed, explicit command syntax
  only. This is still rule-based per this project's constraints, not an
  LLM interpreting free text. (The future natural-language path via
  Alpaca's MCP server, noted in `specs/tasks/backlog.md`, is separate,
  additive, and out of scope here.)
- No budget-tracking commands (`/reset_budget`, `/increase_budget` in
  the sibling project's Telegram bot) — feature 9's auto-entry gate is a
  live buying-power check on every attempt, not a locally-persisted
  counter, so there's nothing to reset or raise.
- No trade-ID concept in `/close` — Alpaca nets one position per symbol
  (confirmed in feature 5's docstring), unlike OANDA's per-trade model,
  so closing is always by symbol.
- No short-selling command — Alpaca crypto is spot-only (per
  `trading.py`'s `open_protected_position` docstring), so there's only
  "buy" (open/add) and "close," no "short."
- No message history/logging beyond what cron's log file (feature 7)
  already captures.
- `DEFAULT_ORDER_NOTIONAL`/`DEFAULT_ORDER_SYMBOL` (see below) are
  command-argument defaults for convenience, not an enforced ceiling —
  they don't change this project's "no preset dollar ceiling" constraint:
  any command can override the amount inline, and nothing in this
  feature validates or caps the value against a hardcoded number.

## Requirements

1. `crypto_bot/telegram_bot.py` exposes:
   - `send_message(settings: Settings, text: str, reply_markup: dict | None = None) -> None`
     — POSTs to `https://api.telegram.org/bot{token}/sendMessage`.
   - `get_updates(settings: Settings, offset: int) -> list[dict]` — GETs
     `.../getUpdates?offset={offset}`, returning raw Telegram update
     dicts.
   - Both raise `TelegramError` on a non-2xx response; never leak the
     bot token (it's part of the URL — error messages must redact it).
2. `crypto_bot/telegram_state.py` tracks `last_update_id` in a small
   local JSON file (`telegram_state.json`, gitignored) so re-processing
   the same message twice across cron ticks doesn't happen.
3. Any update whose `message.chat.id` doesn't match
   `settings.telegram_chat_id` is ignored entirely (not replied to, not
   acted on).
4. `crypto_bot/telegram_commands.py` exposes
   `handle_command(client, data_client, settings, text) -> tuple[str, dict | None]`
   (reply text, optional `reply_markup` for the button keyboard)
   supporting:
   - `/buy SYMBOL [AMOUNT] [TIER]` — calls `open_protected_position`.
     `AMOUNT` optional, defaults to `settings.default_order_notional`
     (see Environment Variables); `TIER` optional, defaults to
     `"moderate"`. Accepts the symbol with or without a slash (`BTC/USD`
     or `BTCUSD`) and normalizes to the slash form the underlying
     functions expect. Invalid tier name, non-numeric amount, or an
     order that doesn't fill all reply with an error instead of raising.
   - `/close SYMBOL` — calls `close_position`, replies with the result
     (fill price, realized context). Same symbol normalization as
     `/buy`.
   - `/positions` — calls `get_open_positions`, formats a one-line-per-
     position reply (symbol, qty, side, entry price, unrealized P/L), or
     "No open positions."
   - `/help` / `/start` — welcome/help text listing the commands above,
     paired with the button keyboard (Requirement 5).
   - Anything else — a short "unknown command" reply listing the
     supported commands, paired with the button keyboard.
5. Persistent reply keyboard (sent alongside `/help`/`/start` replies):
   a "Buy `{DEFAULT_ORDER_SYMBOL}` (\${DEFAULT_ORDER_NOTIONAL})" button
   and a "Positions" button. Tapping "Buy ..." runs the same path as
   `/buy DEFAULT_ORDER_SYMBOL` (default amount, default tier
   `"moderate"`); tapping "Positions" runs the same path as
   `/positions`. Recognize a tap by matching the button's fixed prefix
   (the dollar figure is live and can change between `/help` calls),
   not by prompting further — one tap, one immediate action, no
   confirmation step.
6. `crypto_bot/run_cycle.py` (extending features 7 and 9) `__main__`:
   1. Fetch new Telegram updates, run `handle_command` for each, reply,
      advance `last_update_id`.
   2. If `settings.auto_entry_enabled`, run feature 9's
      `run_auto_entry_cycle` (unchanged call); for each
      `AutoEntryResult` with `action in ("ENTERED",
      "SKIPPED_INSUFFICIENT_FUNDS")`, send a Telegram notification
      naming the symbol, action, and detail. The routine
      `SKIPPED_ALREADY_OPEN`/`SKIPPED_NO_SIGNAL` results are not
      notified — every 2 minutes across 6 symbols would be noise.
   3. Run feature 6's `check_and_reconcile_exits` (unchanged call); for
      each `ReconcileAction` returned, send a Telegram notification
      naming the symbol, action, and detail.
   This becomes the crontab's target command going forward — same
   command as feature 7 already documents
   (`python -m crypto_bot.run_cycle`), no crontab edit needed.

## Design / Approach

```python
# crypto_bot/telegram_bot.py
import requests

from crypto_bot.config import Settings

TELEGRAM_API = "https://api.telegram.org"


class TelegramError(Exception):
    """Raised when a Telegram API call fails."""


def send_message(settings: Settings, text: str, reply_markup: dict | None = None) -> None:
    url = f"{TELEGRAM_API}/bot{settings.telegram_bot_token}/sendMessage"
    payload = {"chat_id": settings.telegram_chat_id, "text": text}
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    resp = requests.post(url, json=payload)
    if not resp.ok:
        raise TelegramError(f"sendMessage failed: {resp.status_code}")


def get_updates(settings: Settings, offset: int) -> list[dict]:
    url = f"{TELEGRAM_API}/bot{settings.telegram_bot_token}/getUpdates"
    resp = requests.get(url, params={"offset": offset, "timeout": 0})
    if not resp.ok:
        raise TelegramError(f"getUpdates failed: {resp.status_code}")
    return resp.json()["result"]
```

`handle_command` does simple `str.split()` parsing — no argument-
parsing library needed for 3 fixed commands plus 2 buttons.

Symbol normalization (`BTCUSD` -> `BTC/USD`) lives in
`telegram_commands.py`, not in `orders.py`/`trading.py`/`exits.py` —
those already take the slash form per their existing docstrings/README
usage, and this feature is the only caller that needs to accept both
from free-text user input.

`run_cycle.py` imports and sequences `telegram_commands.handle_command`,
`strategy.run_auto_entry_cycle` (feature 9, gated on
`settings.auto_entry_enabled`), and `exits.check_and_reconcile_exits` —
no new business logic of its own beyond formatting notification text
from `AutoEntryResult`/`ReconcileAction`, just orchestration +
notification calls, consistent with feature 7's existing "no new
business logic" design.

## Environment Variables / Config

- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` — new, required once this
  feature is implemented (via @BotFather / @userinfobot or similar to
  obtain).
- `DEFAULT_ORDER_NOTIONAL` — new, required once this feature is
  implemented. Dollar amount used by `/buy SYMBOL` (amount omitted) and
  the "Buy" button. Always overridable inline (`/buy SYMBOL 25`); not
  validated against any hardcoded ceiling (see Non-Goals).
- `DEFAULT_ORDER_SYMBOL` — new, optional, defaults to `BTC/USD` if
  unset. Symbol used by the "Buy" button.

## Acceptance Criteria

- [x] `send_message`/`get_updates` build the correct URL/payload
      (including `reply_markup` when provided) and raise `TelegramError`
      (token redacted) on failure — unit-tested with a mocked `requests`.
- [x] An update from a non-matching `chat_id` is ignored — unit-tested.
- [x] `handle_command` parses `/buy`, `/close`, `/positions` correctly
      and calls the right underlying function (mocked) with the right
      arguments, including default amount/tier when omitted and slash
      normalization for both slash and non-slash symbol input.
- [x] Button taps ("Buy ... ($X)", "Positions") dispatch to the same
      handlers as their typed-command equivalents — unit-tested.
- [x] An unrecognized command returns the "unknown command" reply
      (with keyboard) without raising.
- [x] `run_cycle.py` processes commands, then (if enabled) the auto-entry
      cycle, then the reconciliation check, in that order — sends one
      notification per `ENTERED`/`SKIPPED_INSUFFICIENT_FUNDS`
      `AutoEntryResult` and per `ReconcileAction` returned, and makes no
      auto-entry calls at all when `settings.auto_entry_enabled` is
      `False` — unit-tested with mocks for all three stages. Also added
      beyond the original spec text (not a regression, an addition): a
      `TelegramError` during command processing is caught and logged,
      not fatal — the auto-entry/reconciliation steps still run that
      cycle, since those are the safety-critical checks.
- [x] `telegram_state.json` added to `.gitignore`.
- [x] `requests` added to `requirements.txt`.
- [x] README section documenting the supported commands/buttons and how
      to get `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`.
- [ ] Live verification: `send_message` confirmed delivering a real
      Telegram message; `/positions` sent from Telegram and processed via
      `run_cycle`, correct reply logic exercised. `/buy` not forced live
      by default (places a real paper order) — confirm with the user
      before exercising it live; its code path is covered by unit tests
      and shares `open_protected_position`, already verified live in
      feature 8. **Blocked on real `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`/
      `DEFAULT_ORDER_NOTIONAL` in `.env`** — not yet provided as of
      2026-07-11; 130/130 tests pass without them (all mocked), but
      `load_settings()` will raise `ConfigError` for any real script
      invocation until they're set.

## Open Questions

None — resolved with the user before drafting:

- `/buy` amount: configurable default (`DEFAULT_ORDER_NOTIONAL`),
  always overridable inline, not a system-enforced ceiling.
- Button keyboard: included in this feature (Buy default-symbol/-amount,
  Positions), not deferred.
- Command set for v1: `/buy`, `/close`, `/positions`, `/help`/`/start`
  only — no `/balance`.

## Out of Scope / Future Work

- `/balance` (account cash/buying power via `alpaca_client`).
- Webhook-based delivery instead of polling.
- Any command confirmation step (e.g. "are you sure?") before acting —
  commands execute immediately.
- Rich formatting/inline keyboards beyond the one persistent reply
  keyboard — plain text replies only.
- The natural-language command path via Alpaca's MCP server (see
  `specs/tasks/backlog.md`) — separate, additive, needs its own ADR.
- Multi-symbol buttons (currently one configurable default symbol).
