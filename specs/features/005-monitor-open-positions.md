# Feature: Monitor open positions

Status: Done
Depends on: [004-place-market-order](004-place-market-order.md)
Related ADRs: [0002-use-alpaca-py](../adr/0002-use-alpaca-py.md)

## Summary

Read the account's currently open crypto positions from Alpaca and
return them in a structured, per-position form. This is read-only (like
features 2–3) — it changes nothing on the account. It exists so feature
6 (stop-loss/take-profit) has something to evaluate against, and so
there's a simple way to check "what's open right now" without going to
Alpaca's dashboard.

Alpaca's crypto account is netted per symbol (one position per symbol,
not per-trade like OANDA's `OpenTrades`) — there's no separate
"trade ID" concept to track here the way the OANDA sibling project
needed one.

## Goals

- A single function returning all currently open positions on the
  account, in a structured form (symbol, quantity, side, entry price,
  unrealized P/L) — not the raw Alpaca response.
- Cheap to call repeatedly (a plain poll via `get_all_positions`, no
  streaming) — consistent with feature 3's one-shot pricing approach.

## Non-Goals

- No stop-loss/take-profit evaluation — that's feature 6.
- No closing or modifying positions — read-only.
- No persistent polling loop / scheduler — this returns a snapshot for a
  caller to invoke however often it needs; feature 6 decides when/how
  often to call it.
- No streaming position updates — a plain request/response poll is
  enough for this project's scope.

## Requirements

1. `crypto_bot/positions.py` exposes `get_open_positions(client) ->
   list[OpenPosition]`.
2. `OpenPosition` is a frozen dataclass: `symbol: str` (confirmed live:
   `Position.symbol` comes back **without** the slash, e.g. `BTCUSD` —
   the opposite of `Order.symbol`, which keeps the slash, e.g.
   `BTC/USD`. This is convenient here: a `Position.symbol` value can be
   passed directly to `close_position`/`get_open_position`, which expect
   the no-slash form, with no conversion needed — see feature 4's
   symbol-format note for the order-side half of this inconsistency),
   `qty: Decimal` (fractional, can be very small), `side: Literal["long",
   "short"]`, `avg_entry_price: Decimal`, `unrealized_pl: Decimal`.
3. Built via `TradingClient.get_all_positions()`.
4. No open positions is a normal result: an empty list, not an error.
5. On `alpaca.common.exceptions.APIError`, wrap it in a `PositionError`
   (mirroring `AlpacaAuthError`/`MarketDataError`/`OrderError`) with a
   clear message; never leak the API key/secret.
6. `python -m crypto_bot.positions` prints all open positions in
   human-readable form (or a clear "no open positions" message).
   Read-only, safe to run anytime — same category of check as features
   2–3, unlike feature 4.

## Design / Approach

Mirrors `crypto_bot/market_data.py`'s shape:

```python
# crypto_bot/positions.py
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from alpaca.common.exceptions import APIError
from alpaca.trading.client import TradingClient


class PositionError(Exception):
    ...


@dataclass(frozen=True)
class OpenPosition:
    symbol: str
    qty: Decimal
    side: Literal["long", "short"]
    avg_entry_price: Decimal
    unrealized_pl: Decimal


def get_open_positions(client: TradingClient) -> list[OpenPosition]:
    try:
        positions = client.get_all_positions()
    except APIError as exc:
        raise PositionError("Failed to fetch open positions") from exc

    return [
        OpenPosition(
            symbol=p.symbol,
            qty=Decimal(str(p.qty)),
            side="long" if str(p.side).split(".")[-1].lower() == "long" else "short",
            avg_entry_price=Decimal(str(p.avg_entry_price)),
            unrealized_pl=Decimal(str(p.unrealized_pl)),
        )
        for p in positions
    ]


if __name__ == "__main__":
    import logging

    from crypto_bot.config import load_settings
    from crypto_bot.alpaca_client import get_client

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    settings = load_settings()
    client = get_client(settings)
    positions = get_open_positions(client)

    if not positions:
        print("No open positions.")
    else:
        for p in positions:
            print(
                f"{p.symbol}  qty={p.qty}  side={p.side}  "
                f"entry={p.avg_entry_price}  unrealized_pl={p.unrealized_pl}"
            )
```

## Environment Variables / Config

None new — reuses feature 1/2 config and client.

## Acceptance Criteria

- [ ] `get_open_positions` returns a list of `OpenPosition` matching a
      mocked `get_all_positions` response with one or more positions
      (correct field mapping, `qty`/`avg_entry_price`/`unrealized_pl` as
      `Decimal`).
- [ ] `get_open_positions` returns `[]` when the mocked response has no
      positions — not an error.
- [ ] An `APIError` from the client is wrapped in `PositionError`,
      message never contains the API key/secret.
- [ ] `python -m crypto_bot.positions`, run against the real paper
      account, prints the position opened in feature 4 (or "no open
      positions" if it's since been closed).

## Open Questions

None.

## Out of Scope / Future Work

- Deciding a polling cadence / continuous monitoring loop — deferred to
  feature 6, where it's actually needed to act on the data.
- Streaming updates instead of polling.
