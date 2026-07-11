# Feature: Stop-loss/take-profit (single live Stop Limit order, tracked take-profit target)

Status: Done
Depends on: [004-place-market-order](004-place-market-order.md), [005-monitor-open-positions](005-monitor-open-positions.md)
Related ADRs: [0004-manual-stop-loss-take-profit-for-crypto](../adr/0004-manual-stop-loss-take-profit-for-crypto.md), [0005-single-live-exit-order-per-position](../adr/0005-single-live-exit-order-per-position.md)

## Summary

Attach a stop-loss to a position right after it opens, computed once
(not re-evaluated against a fixed entry price on a recurring poll loop
— see `CLAUDE.md`/`constraints.md`), and track a take-profit target
alongside it. Since Alpaca doesn't support bracket/OCO orders for
crypto, and (discovered live, 2026-07-10, ADR 0005) doesn't even allow
**two independent full-quantity sell orders on the same position at
once** — the first sell order locks the entire position balance,
leaving nothing for a second — only one exit order is ever live:

- **Stop-loss**: a **Stop Limit** sell order, submitted immediately.
  `limit_price` is the true floor — the worst price you're willing to
  accept, guaranteed never violated by how limit orders work.
  `stop_price` (the trigger) sits *above* `limit_price` by a tier-scaled
  buffer, giving the order room to actually execute before the market
  reaches the hard floor. This is the safety-critical leg, so it gets
  continuous, instant, exchange-side enforcement.
- **Take-profit**: not a live order at all — just a tracked target
  price, persisted locally. The reconciliation check (feature 7's cron)
  compares current price against it every run; once reached, the
  stop-loss order is canceled and a market sell realizes the gain. This
  means take-profit realization is bound to the cron cadence (~2
  minutes), not instant — acceptable since it only affects the upside,
  not the stop-loss's safety property.
- **Backstop**: if price has crossed the stop-loss trigger but the Stop
  Limit order is still sitting unfilled (the real failure mode of a
  Stop Limit — a fast move can blow through both the stop and limit
  price, leaving the order permanently unable to fill), the same
  reconciliation check cancels it and submits a plain **market** sell
  instead, guaranteeing an eventual exit at the cost of an unpredictable
  fill price in that scenario.

## Goals

- Compute stop-loss/take-profit prices once, right after a position
  opens, from its actual average entry price (not a pre-fill estimate).
- Attach the stop-loss as a live order immediately; persist the
  take-profit target without submitting it as an order.
- A periodic check (feature 7's cron) that: realizes the take-profit
  once price reaches it, and force-market-sells if the stop-loss order
  is stuck unfilled despite price having crossed its trigger.
- Three risk tiers (conservative/moderate/aggressive), applied uniformly
  to every position this bot opens, manual or automated.

## Non-Goals

- No trailing stops, breakeven moves, or partial closes.
- No change to manual `/close`-equivalent behavior (not yet built) —
  closing a position on demand should still work regardless of any
  attached stop-loss; canceling the now-orphaned stop-loss order on a
  manual close is a concern for whenever that command is built, not
  this feature.

## Requirements

1. `crypto_bot/exits.py` exposes `get_atr(data_client, symbol,
   period=14) -> Decimal`, fetching hourly bars via
   `CryptoHistoricalDataClient.get_crypto_bars` and computing the
   average true range the same way as the OANDA sibling project
   (`max(high-low, |high-prev_close|, |low-prev_close|)`, averaged over
   `period` bars).
2. Distances are ATR-based, computed once at attach time, using
   per-tier multipliers carried over directly from the OANDA project's
   proven three-tier table (confirmed against real BTC/USD data
   2026-07-10: hourly ATR ≈ $340, ≈0.53% of price at the time):

   | Tier | Stop multiplier | Target multiplier | Buffer multiplier |
   |---|---|---|---|
   | Conservative | 1.5x | 2.5x | 0.25x |
   | Moderate | 3x | 6x | 0.5x |
   | Aggressive | 6x | 15x | 1x |

   `target_price = entry_price + (ATR × target_multiplier)`,
   `limit_price = entry_price - (ATR × stop_multiplier)`,
   `stop_price = limit_price + (ATR × buffer_multiplier)`. The buffer
   multiplier is fixed at `stop_multiplier ÷ 6` per tier.
3. `crypto_bot/exits.py` exposes `get_price_increment(client, symbol) ->
   Decimal`, fetching the asset's real price precision via
   `client.get_asset(symbol)`. Confirmed live: BTC/USD's
   `price_increment` is `1e-9`, and Alpaca rejects a submitted price with
   more decimal places than that (`"limit price exceeds maximum
   precision"`) — ATR-derived prices routinely have more decimals than
   that from plain `Decimal` division, so all three prices are
   `.quantize()`d to this increment before submitting.
4. `crypto_bot/exits.py` exposes `attach_protective_orders(client,
   data_client, symbol, qty, entry_price, tier) -> ProtectiveOrders`,
   where `tier: Literal["conservative", "moderate", "aggressive"]`
   selects the multiplier row from #2, computes and quantizes the three
   prices, submits **only** the Stop Limit sell order (`side=SELL`,
   `time_in_force=GTC`), and persists the take-profit target — **does
   not** submit a take-profit order (see ADR 0005 for why two
   independent full-quantity sell orders on the same position doesn't
   work on Alpaca).
5. `stop_price > limit_price` is enforced in code before submitting
   anything (raise `ValueError` rather than silently submit an inverted
   pair).
6. `crypto_bot/exit_state.py` persists, per symbol: the stop-loss
   order ID, the tracked take-profit target price, and the tier used
   (Alpaca's `Position` model has no tagging field for arbitrary
   metadata, confirmed empirically — so this project tracks all of it
   itself, in a small gitignored JSON file, mirroring the OANDA sibling
   project's minimal state-file pattern).
7. `crypto_bot/exits.py` exposes `check_and_reconcile_exits(client,
   data_client) -> list[ReconcileAction]`, run on the project's cron
   cycle (feature 7): for each tracked position, checks the stop-loss
   order's status — if filled, stop tracking (nothing left to do); if
   orphaned (canceled/expired/rejected, e.g. a manual close elsewhere),
   stop tracking; otherwise compares current price against both the
   take-profit target (realize it: cancel the stop-loss, submit a
   market sell) and the stop-loss trigger (backstop: same action, if
   the stop-loss order is still unfilled despite price crossing it).
8. On `alpaca.common.exceptions.APIError`, wrap it in an `ExitError`
   with a clear message; never leak the API key/secret.

## Design / Approach

Implemented in `crypto_bot/exits.py` (constants, `get_atr`,
`get_price_increment`, `attach_protective_orders`,
`check_and_reconcile_exits`) and `crypto_bot/exit_state.py` (persisted
mapping). See those files for the exact implementation — this section
records what was confirmed empirically while building it:

- Confirmed live (2026-07-10) that submitting a take-profit Limit order
  and a stop-loss Stop Limit order simultaneously fails: the first
  order locks the entire position's `qty_available` to `0`, and the
  second is rejected with `"insufficient balance"`. This is why only
  the stop-loss is ever a live order (ADR 0005).
- Confirmed live that a lone Stop Limit sell order for the full position
  quantity is accepted and sits as `status=NEW`, holding the whole
  position's balance against it (expected and fine, since there's no
  competing order anymore).
- Confirmed live that `get_crypto_bars` returns real hourly OHLC data
  suitable for `get_atr`, and that BTC/USD's actual hourly ATR at the
  time was ≈$340 (≈0.53% of the ≈$64,100 price).
- Confirmed live that Alpaca rejects prices exceeding an asset's real
  `price_increment` (BTC/USD: `1e-9`), fixed by quantizing all three
  computed prices to it via `get_price_increment`.
- Confirmed live end-to-end: opened a real paper position, attached a
  stop-loss via `attach_protective_orders`, ran
  `check_and_reconcile_exits` (correctly did nothing, price between
  stop and target), then canceled/closed everything to clean up.

## Environment Variables / Config

None new. `RISK_TIER_ATR_MULTIPLIERS`/`DEFAULT_ATR_PERIOD` are fixed
module-level constants, not user-configurable at this stage.

## Acceptance Criteria

- [x] `get_atr` computes the correct average true range from a mocked
      multi-bar response.
- [x] `get_price_increment` parses a mocked asset response; wraps
      `APIError` without leaking credentials.
- [x] `attach_protective_orders` computes `target_price`/`limit_price`/
      `stop_price` correctly from a mocked ATR value for all three
      tiers, quantizes to the asset's price increment, submits **only**
      the Stop Limit order, persists the take-profit target, and raises
      before submitting anything if `stop_price <= limit_price`.
- [x] Unit tests (mocked client, no network) cover: normal attach for
      all three tiers; inverted stop/limit raises before any request;
      `APIError` wrapped in `ExitError` without leaking credentials.
      45/45 project tests passing.
- [x] `check_and_reconcile_exits` realizes the take-profit (cancels the
      stop-loss, submits a market sell) once price reaches the tracked
      target (mocked).
- [x] `check_and_reconcile_exits` force-market-sells when the stop-loss
      order is stuck unfilled past its trigger (mocked).
- [x] `check_and_reconcile_exits` does nothing when price is between the
      stop and target (mocked), and cleans up orphaned/canceled tracked
      orders without raising.
- [x] Run live against the real paper account: opened a $10 BTC/USD
      position, attached a stop-loss at the expected ATR-derived prices
      (confirmed via Alpaca's own order data), ran the reconciliation
      check (correctly took no action), then canceled the order and
      closed the position to clean up.

## Open Questions

None.

## Out of Scope / Future Work

- The scheduling/cron mechanism itself is feature 7, not this spec.
- Trailing stops, breakeven moves, partial closes.
- Reducing take-profit realization latency below the cron cadence (e.g.
  a streaming price feed) — not needed at this project's scale.
