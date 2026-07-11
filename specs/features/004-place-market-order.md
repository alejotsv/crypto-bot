# Feature: Place a basic market order (buy/sell)

Status: Done
Depends on: [003-fetch-live-price-data](003-fetch-live-price-data.md)
Related ADRs: [0002-use-alpaca-py](../adr/0002-use-alpaca-py.md), [0003-paper-account-until-explicit-go-live](../adr/0003-paper-account-until-explicit-go-live.md)

## Summary

Place a plain market order (buy or sell) for a crypto pair via Alpaca's
`TradingClient.submit_order`, using the authenticated client from
feature 2. This is the first feature that actually changes state on the
account — unlike features 2–3 (read-only), running this **opens or
closes a real position** on whichever account `.env` points at (fake
money on paper, real money on live). No stop-loss/take-profit attached
here — that's feature 6, built as separate Limit/Stop Limit orders per
ADR 0004 (Alpaca doesn't support bracket orders for crypto at all).

**Confirmed live (2026-07-10) against the real paper account, a real
mechanical difference from the OANDA sibling project worth designing
around from the start:** Alpaca's order submission is **asynchronous**.
`submit_order` returns immediately with the order in `PENDING_NEW`
status, not filled — unlike OANDA, which resolves a market order
synchronously in one response with the fill embedded. The actual fill
(price, filled quantity) only appears on a **follow-up** call
(`get_order_by_id`), typically ready within about a second in practice,
but not guaranteed to be immediate. This feature must poll for the
terminal status rather than assume the `submit_order` response is final.

## Goals

- A single function to place a market order for a crypto pair, with an
  explicit `side` ("buy"/"sell") using Alpaca's own `OrderSide` enum
  directly (no need to reinvent a signed-units convention — Alpaca
  already takes side and a positive quantity separately, unlike OANDA's
  signed-units convention).
- Handle Alpaca's asynchronous fill: submit, then poll `get_order_by_id`
  until a terminal status (`filled`, `rejected`, `canceled`, etc.) is
  reached, with a bounded timeout — not an unbounded wait.
- A clear, structured result: was the order filled or not, at what
  price, how much quantity — not the raw Alpaca `Order` object.
- Handle a rejected/unfilled order as a normal, expected result — not an
  exception.

## Non-Goals

- No stop-loss/take-profit attached to the order — that's feature 6.
- No position sizing / dollar-budget logic — this feature places
  whatever `notional` (dollar amount) or `qty` it's given, no enforcement
  of any spending cap here (see `specs/context/constraints.md` — no
  preset ceiling is designed into this project at all).
- No limit or stop-limit orders — market orders only (feature 6 adds
  those for exits).
- No order modification or cancellation beyond what's needed to clean up
  a test order while building this feature.

## Requirements

1. `crypto_bot/orders.py` exposes `place_market_order(client, symbol,
   side, notional) -> OrderResult`, where `side: Literal["buy", "sell"]`
   and `notional: Decimal` is a dollar amount (not a unit/share count —
   crypto is fractional, and pricing in dollars matches how this
   project already thinks about position sizing). **Alpaca enforces a
   $10 minimum notional per crypto order** (confirmed live: a $2 test
   order was rejected with `"cost basis must be >= minimal amount of
   order 10"`) — this feature validates that before submitting, raising
   `ValueError` rather than letting Alpaca's rejection be the first
   sign of the problem.
2. Built via `alpaca.trading.requests.MarketOrderRequest` (`symbol`,
   `notional`, `side`, `time_in_force=TimeInForce.GTC` — crypto doesn't
   support `DAY`, only `gtc`/`ioc`/`fok`), submitted via
   `TradingClient.submit_order`.
3. After submission, poll `get_order_by_id` (bounded retries with a
   short sleep between attempts — exact interval/count is an
   implementation detail, not fixed here) until `status` is a terminal
   value (`filled`, `rejected`, `canceled`, `expired`) or the poll budget
   is exhausted (raise `OrderError` in that last case — a market order
   in an active 24/7 crypto market taking unreasonably long to resolve
   is itself worth surfacing as an error, not silently returning an
   incomplete result).
4. `OrderResult` is a frozen dataclass capturing: `status`
   (`Literal["FILLED", "REJECTED", "CANCELED"]`, collapsing Alpaca's
   broader enum to the outcomes this project actually acts on),
   `order_id: str`, `symbol: str`, `side: Literal["buy", "sell"]`,
   `filled_qty: Decimal | None`, `filled_avg_price: Decimal | None`.
5. On `alpaca.common.exceptions.APIError`, wrap it in an `OrderError`
   (mirroring `AlpacaAuthError`/`MarketDataError`) with a clear message;
   never leak the API key/secret.
6. Validate inputs before calling Alpaca: `notional` must be `>= 10`
   (raise `ValueError` otherwise); `side` must be `"buy"` or `"sell"`.
7. `python -m crypto_bot.orders` places a **minimal $10 market buy**
   order on `BTC/USD` against the real paper account, and prints the
   resulting `OrderResult`. Like the OANDA sibling project's equivalent
   check, this one has a real (paper-money) side effect — the script
   output must make this unambiguous.

## Design / Approach

```python
# crypto_bot/orders.py
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from alpaca.common.exceptions import APIError
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest

MIN_NOTIONAL = Decimal("10")
POLL_INTERVAL_SECONDS = 1
MAX_POLL_ATTEMPTS = 10
TERMINAL_STATUSES = {"filled", "rejected", "canceled", "expired"}


class OrderError(Exception):
    ...


@dataclass(frozen=True)
class OrderResult:
    status: Literal["FILLED", "REJECTED", "CANCELED"]
    order_id: str
    symbol: str
    side: Literal["buy", "sell"]
    filled_qty: Decimal | None
    filled_avg_price: Decimal | None


def place_market_order(
    client: TradingClient,
    symbol: str,
    side: Literal["buy", "sell"],
    notional: Decimal,
) -> OrderResult:
    if notional < MIN_NOTIONAL:
        raise ValueError(f"notional must be >= {MIN_NOTIONAL}, got {notional}")
    if side not in ("buy", "sell"):
        raise ValueError(f"side must be 'buy' or 'sell', got {side!r}")

    order_data = MarketOrderRequest(
        symbol=symbol,
        notional=notional,
        side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
        time_in_force=TimeInForce.GTC,
    )
    try:
        order = client.submit_order(order_data)
    except APIError as exc:
        raise OrderError(f"Failed to place {side} order for {symbol}") from exc

    for _ in range(MAX_POLL_ATTEMPTS):
        try:
            order = client.get_order_by_id(order.id)
        except APIError as exc:
            raise OrderError(f"Failed to check order status for {symbol}") from exc
        if str(order.status).split(".")[-1].lower() in TERMINAL_STATUSES:
            break
        time.sleep(POLL_INTERVAL_SECONDS)
    else:
        raise OrderError(f"Order for {symbol} did not reach a terminal status in time")

    status_name = str(order.status).split(".")[-1].upper()
    return OrderResult(
        status=status_name if status_name in ("FILLED", "REJECTED", "CANCELED") else "REJECTED",
        order_id=str(order.id),
        symbol=symbol,
        side=side,
        filled_qty=Decimal(str(order.filled_qty)) if order.filled_qty else None,
        filled_avg_price=Decimal(str(order.filled_avg_price)) if order.filled_avg_price else None,
    )


if __name__ == "__main__":
    import logging

    from crypto_bot.config import load_settings
    from crypto_bot.alpaca_client import get_client

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    settings = load_settings()
    client = get_client(settings)

    print(
        "Placing a REAL $10 market BUY order for BTC/USD on your "
        f"{'paper' if settings.alpaca_paper else 'LIVE'} account..."
    )
    result = place_market_order(client, "BTC/USD", "buy", Decimal("10"))
    print(result)
```

### A real symbol-format gotcha, confirmed live

Order submission uses the slash format (`BTC/USD`). But closing a
position or looking one up by symbol (feature 5/6) requires the **no-
slash** format (`BTCUSD`) instead — confirmed empirically: submitting an
order with `symbol="BTC/USD"` and later calling
`client.close_position("BTC/USD")` returns a 404; `client
.close_position("BTCUSD")` works. `get_all_positions()` itself reports
`symbol='BTC/USD'` (with slash) on the returned `Position` object, which
is *not* the format its own `close_position`/`get_open_position` calls
expect by symbol — an inconsistency in Alpaca's own API, not something
this project is choosing. Worth handling explicitly (e.g. a small helper
to strip the slash) wherever a symbol is used to look up or close a
position, not just to place an order.

## Environment Variables / Config

None new — reuses feature 1/2 config and client.

## Acceptance Criteria

- [ ] `place_market_order` returns `OrderResult(status="FILLED", ...)`
      with correct `filled_avg_price`/`filled_qty` (as `Decimal`) once
      polling reaches a terminal status, confirmed against a mocked
      client (no real network in the unit test).
- [ ] `place_market_order` returns a non-`FILLED` result when the mocked
      order resolves to `rejected`/`canceled` instead — not an exception.
- [ ] `notional < 10` raises `ValueError` before any request is made.
- [ ] An `APIError` from the client (on submit or on status polling) is
      wrapped in `OrderError`, message never contains the API key/secret.
- [ ] Polling that never reaches a terminal status within
      `MAX_POLL_ATTEMPTS` raises `OrderError` rather than returning a
      misleading result.
- [ ] `python -m crypto_bot.orders`, run against the real paper account,
      places a $10 BTC/USD market buy and prints a `FILLED` result with
      real `filled_avg_price`.
- [ ] README updated: clearly marks this check as having a real (paper)
      side effect, the $10 minimum notional, and the `BTC/USD` vs
      `BTCUSD` symbol-format gotcha.

## Open Questions

None. Exact poll interval/attempt count are implementation details, not
fixed here — confirmed live that a fill is typically ready within about
a second, so a short interval with a handful of retries is a reasonable
starting point, adjustable if it proves too tight or too slow in
practice.

## Out of Scope / Future Work

- Attaching stop-loss/take-profit at order creation — not possible for
  crypto on Alpaca at all (ADR 0004); feature 6 builds this separately.
- Position sizing/risk rules, live spending limits.
- Limit/stop-limit orders (feature 6 adds these for exits specifically).
- Order modification/cancellation as a general capability.
