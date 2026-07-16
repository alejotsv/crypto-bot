# crypto-bot

A crypto trading bot for Alpaca's API, built as a personal learning
project to understand algorithmic trading mechanics before adding any
AI/LLM layer. See `CLAUDE.md` for the full project context and
spec-driven workflow, and `specs/` for feature specs, ADRs, and the
backlog.

**Paper trading account only**, unless you've explicitly decided to move
to live trading — see
`specs/adr/0003-paper-account-until-explicit-go-live.md`.

## Setup

Requires Python 3.11+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Copy the example env file and fill in your values:

```bash
cp .env.example .env
```

### Getting your Alpaca credentials

1. Create an account at [alpaca.markets](https://alpaca.markets) if you
   don't have one. Account activation may be required before the API
   Keys section becomes visible.
2. Log in, switch to the **Paper Trading** account (dropdown/toggle,
   upper-left), and generate an API key/secret pair — this is
   `ALPACA_API_KEY`/`ALPACA_SECRET_KEY`.
3. Leave `ALPACA_PAPER=true` and `ALPACA_BASE_URL=https://paper-api.alpaca.markets`
   as shipped in `.env.example`. `ALPACA_BASE_URL` is required (not
   inferred from `ALPACA_PAPER`) as a deliberate fail-safe — the two
   must agree, or `load_settings()` refuses to start rather than risk
   running against the wrong environment.

## Running tests

```bash
source .venv/bin/activate
pytest
```

The test suite requires no network access and no real credentials.

## Checking your connection

```bash
source .venv/bin/activate
python -m crypto_bot.alpaca_client
```

Read-only — prints account status, currency, cash, and buying power to
confirm your credentials work.

## Checking live price data

```bash
source .venv/bin/activate
python -m crypto_bot.market_data
```

Read-only — prints the current BTC/USD bid/ask/spread. Crypto symbols
use Alpaca's `BASE/QUOTE` format (e.g. `BTC/USD`, slash not underscore).

## Placing a market order

```bash
source .venv/bin/activate
python -m crypto_bot.orders
```

**This has a real (paper-money) side effect** — places a real $10 BTC/USD
market buy order. Alpaca enforces a $10 minimum notional per crypto
order. Order submission is asynchronous (unlike some brokers) — the
script polls until the order reaches a terminal status before printing
the result.

## Checking open positions

```bash
source .venv/bin/activate
python -m crypto_bot.positions
```

Read-only — lists open positions (symbol, quantity, side, entry price,
unrealized P/L), or prints "No open positions." Note: a position's
`symbol` comes back **without** a slash (e.g. `BTCUSD`), the opposite of
an order's `symbol` (`BTC/USD`) — a real Alpaca API inconsistency, not a
choice made here.

## Stop-loss/take-profit

Alpaca doesn't support bracket/OCO orders for crypto, and doesn't even
allow two independent full-quantity sell orders on the same position at
once (see `specs/adr/0004-manual-stop-loss-take-profit-for-crypto.md`
and `specs/adr/0005-single-live-exit-order-per-position.md`). So only
the **stop-loss** is ever a live order on Alpaca — a Stop Limit sell
order, computed once from ATR (Average True Range) and a risk tier
(conservative/moderate/aggressive), enforced instantly by Alpaca's own
matching engine. The **take-profit** is just a tracked target price,
realized by the reconciliation check (see below) once price reaches it.

## Opening a protected position (recommended)

```python
from decimal import Decimal
from crypto_bot.config import load_settings
from crypto_bot.alpaca_client import get_client
from crypto_bot.trading import open_protected_position
from alpaca.data.historical.crypto import CryptoHistoricalDataClient

settings = load_settings()
client = get_client(settings)
data_client = CryptoHistoricalDataClient(
    api_key=settings.alpaca_api_key, secret_key=settings.alpaca_secret_key
)
result = open_protected_position(client, data_client, "BTC/USD", Decimal("10"), "moderate")
```

Places the entry order, then attaches a stop-loss sized from the
position's **actual** quantity — not the order's `filled_qty`. Those two
differ (confirmed live): Alpaca deducts its crypto trading fee from the
asset itself, so `filled_qty` overstates real holdings by roughly the
fee percentage. Calling `attach_protective_orders` directly with
`filled_qty` fails with an "insufficient balance" error on an otherwise
normal trade — use `open_protected_position` instead of wiring
`place_market_order` + `attach_protective_orders` together by hand.

## Closing a position

```python
from crypto_bot.exits import close_position
close_position(client, "BTC/USD")
```

Cancels any tracked stop-loss order first, then closes the position.
This order matters: Alpaca refuses to close a position while a sell
order still holds its balance (confirmed live — it fails with
"insufficient balance", not a silent orphan), so closing a position
outside this function (e.g. via Alpaca's dashboard) requires manually
canceling its stop-loss order first.

## Automated entry (optional)

```bash
source .venv/bin/activate
python -m crypto_bot.run_cycle
```

If `AUTO_ENTRY_ENABLED=true` in `.env`, each `run_cycle` invocation also
checks a fixed set of 6 symbols for a buy signal before running the exit
reconciliation check below:

`BTC/USD`, `ETH/USD`, `AAVE/USD`, `UNI/USD`, `PAXG/USD`, `XRP/USD`

The signal (see `specs/adr/0007-bollinger-squeeze-breakout-entry-signal.md`
for why this replaced the original 5/20 SMA crossover): a Bollinger Band
squeeze breakout on hourly bars — Bollinger Bands (20-period basis, ±2
standard deviations) contracting fully inside a Keltner Channel (same
basis, ±1.5× the 14-period ATR) is a low-volatility "squeeze"; the
signal fires on the specific hour that squeeze releases (bands expand
back outside the channel), provided the live price is above the basis
line at that moment (confirms an upward breakout, not a downward one).
If true, no position is already open for that symbol, and the account's
real spendable cash (Alpaca's `non_marginable_buying_power` — the
correct field for crypto, since crypto trading is spot/cash-only and
`buying_power` is inflated by the equities margin multiplier) covers
`AUTO_ENTRY_NOTIONAL`, it opens a protected position exactly like a
manual `open_protected_position` call — stop-loss attached instantly,
`tier` fixed at `moderate`.

The primary spending gate is always the live buying-power check above —
every attempt checks real account funds fresh, so it can't drift out of
sync with what's actually in the account. `AUTO_ENTRY_ENABLED` defaults
to `false`: this feature does nothing until you opt in.

On top of that, two **optional** spending caps (see
`specs/adr/0006-optional-auto-entry-spending-caps.md`) apply to
auto-entry only — never to manual trades:

- `AUTO_ENTRY_TOTAL_CAP` (default `1000`) — a lifetime cumulative dollar
  ceiling on auto-entry spend. Never resets automatically; once reached,
  auto-entry stays blocked until you edit `.env`/the state file by hand.
- `AUTO_ENTRY_DAILY_CAP` (default `200`) — same idea, but resets
  automatically each UTC calendar day.

For each, `0` disables that cap entirely; any value `>0` enables it at
that dollar amount. Cumulative spend is tracked in
`auto_entry_spend_state.json` (gitignored), only incremented when a
trade actually fills.

## Telegram bot

Telegram is the control surface for manual trading and the alert
channel for anything the bot does automatically.

### Getting your Telegram credentials

1. Message [@BotFather](https://t.me/BotFather) on Telegram, send
   `/newbot`, and follow the prompts — this gives you
   `TELEGRAM_BOT_TOKEN`.
2. Send your new bot any message (e.g. `/start`), then message
   [@userinfobot](https://t.me/userinfobot) (or similar) to find your
   own numeric chat ID — this is `TELEGRAM_CHAT_ID`.
3. Set both, plus `DEFAULT_ORDER_NOTIONAL` (the dollar amount `/buy`
   uses when you don't specify one — required, no code default) in
   `.env`. `DEFAULT_ORDER_SYMBOL` is optional, defaults to `BTC/USD`.

### Commands

- `/buy SYMBOL [AMOUNT] [TIER]` — buys and protects a symbol in one
  action (entry + stop-loss attached, via `open_protected_position`).
  `AMOUNT` defaults to `DEFAULT_ORDER_NOTIONAL`; `TIER` defaults to
  `moderate` (`conservative`/`moderate`/`aggressive`). Accepts the
  symbol with or without a slash (`BTC/USD` or `BTCUSD`).
- `/close SYMBOL` — closes an open position (cancels any tracked
  stop-loss first, then closes).
- `/positions` — lists open positions, or replies "No open positions."
- `/help` / `/start` — shows the command list, paired with a persistent
  reply-keyboard button for one-tap buying the default symbol/amount and
  one for listing positions.

Only messages from `TELEGRAM_CHAT_ID` are ever acted on — anything from
another chat is silently ignored, not replied to.

### Notifications

The bot proactively messages you (no command needed) whenever:

- Auto-entry (if enabled) opens a position, or is blocked specifically
  for lack of funds — the routine "no signal"/"already open" skips are
  not notified, since across 6 symbols every 2 minutes that would be
  noise.
- The exit reconciliation check realizes a take-profit or force-sells a
  stuck stop-loss.

There's no webhook — since nothing in this project runs a persistent
server, inbound commands are picked up by polling Telegram's
`getUpdates` once per cron cycle (see below), tracked in
`telegram_state.json` (gitignored) so the same message never gets
processed twice.

## Running continuously (cron)

```bash
source .venv/bin/activate
python -m crypto_bot.run_cycle
```

Each invocation, in order: processes any pending Telegram commands and
replies, runs the auto-entry check above (if enabled) and notifies on
it, then runs the exit reconciliation check (realizes the take-profit
target if price has reached it, force-market-sells a stop-loss order
that's stuck unfilled despite price crossing its trigger) and notifies
on it. A Telegram outage during command processing is logged and
skipped, not fatal — the auto-entry/reconciliation steps still run. No
persistent process — invoke this repeatedly via cron.

Crontab entry (runs every 2 minutes):

```
*/2 * * * * cd /home/pi/crypto-bot && .venv/bin/python -m crypto_bot.run_cycle >> logs/reconcile.log 2>&1
```

If this is running on the same Raspberry Pi as the `trading-bot`
sibling project, that's fine — separate repo, separate `.env`, separate
log file, separate crontab line; no shared state between the two.

Setup on the Pi:

```bash
git clone <your-repo-url> ~/crypto-bot
cd ~/crypto-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env  # fill in real credentials
mkdir -p logs
crontab -e  # add the line above
```

Confirm it's running: `tail -f logs/reconcile.log`.
