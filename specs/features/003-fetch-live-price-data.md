# Feature: Fetch live price data (a crypto pair)

Status: Done
Depends on: [002-alpaca-authentication](002-alpaca-authentication.md)
Related ADRs: [0002-use-alpaca-py](../adr/0002-use-alpaca-py.md)

## Summary

Fetch a current bid/ask price snapshot for a crypto pair (BTC/USD to
start) from Alpaca's crypto market data API. This is a one-shot price
*snapshot* (poll), not a persistent streaming connection — simpler to
reason about, and enough to understand how Alpaca represents crypto
price data before any polling loop or strategy logic is built on top of
it.

## Goals

- A single function that returns the current bid, ask, and spread for a
  given crypto pair (defaulting to BTC/USD) as precise, comparison-safe
  values — not floats.
- Same manual-verification pattern as feature 2: a runnable check
  against the real paper account that prints the current price.

## Non-Goals

- No streaming/persistent connection — polling only.
- No historical/candlestick (bars) data — a different endpoint, not
  needed yet.
- No polling loop, scheduling, or caching — this feature fetches once
  per call; anything continuous is future work.
- No multi-pair batching — single pair per call, BTC/USD as the default.

## Requirements

1. `crypto_bot/market_data.py` exposes `get_price(client,
   symbol="BTC/USD") -> PriceQuote`, using
   `alpaca.data.historical.crypto.CryptoHistoricalDataClient` and
   `get_crypto_latest_quote`. Note this uses a *different* client class
   than `TradingClient` (feature 2) — Alpaca splits trading and market
   data into separate clients, both authenticated with the same
   key/secret.
2. `PriceQuote` is a frozen dataclass: `symbol: str`, `time:
   datetime` (Alpaca returns a real `datetime`, unlike OANDA's ISO
   string), `bid: Decimal`, `ask: Decimal`, plus a `spread` property
   (`ask - bid`).
3. Bid/ask are converted to `Decimal` via `Decimal(str(value))`, never
   `Decimal(value)` directly on Alpaca's float — this doesn't fully
   avoid the float round-trip (Alpaca's SDK already parses the JSON
   number into a `float` before this code ever sees it, so some
   precision risk is inherent and outside this project's control), but
   `Decimal(str(...))` avoids compounding it further with a second,
   avoidable conversion artifact. Worth noting as a real (if narrow)
   difference from the OANDA sibling project, which parses `Decimal`
   directly from untouched strings with no float step at all.
4. Crypto symbols use Alpaca's `BASE/QUOTE` format (e.g. `BTC/USD`,
   slash not underscore) — different from OANDA's `EUR_USD` convention,
   worth calling out since it's an easy trip-up switching between the
   two sibling projects.
5. On request failure, wrap the underlying `alpaca.common.exceptions
   .APIError` in a `MarketDataError` (mirroring `AlpacaAuthError` from
   feature 2) with a clear message; never leak the API key/secret.
6. `python -m crypto_bot.market_data` fetches and prints the current
   BTC/USD price (symbol, bid, ask, spread) using the real paper account
   from `.env` — same manual-verification pattern as feature 2. Crypto
   markets trade 24/7 — unlike the OANDA sibling project, there's no
   `tradeable`/market-hours flag to surface here.

## Design / Approach

```python
# crypto_bot/market_data.py
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime

from alpaca.common.exceptions import APIError
from alpaca.data.historical.crypto import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoLatestQuoteRequest


class MarketDataError(Exception):
    ...


@dataclass(frozen=True)
class PriceQuote:
    symbol: str
    time: datetime
    bid: Decimal
    ask: Decimal

    @property
    def spread(self) -> Decimal:
        return self.ask - self.bid


def get_price(client: CryptoHistoricalDataClient, symbol: str = "BTC/USD") -> PriceQuote:
    request = CryptoLatestQuoteRequest(symbol_or_symbols=symbol)
    try:
        quotes = client.get_crypto_latest_quote(request)
    except APIError as exc:
        raise MarketDataError(f"Failed to fetch price for {symbol}") from exc

    quote = quotes[symbol]
    return PriceQuote(
        symbol=symbol,
        time=quote.timestamp,
        bid=Decimal(str(quote.bid_price)),
        ask=Decimal(str(quote.ask_price)),
    )


if __name__ == "__main__":
    import logging

    from crypto_bot.config import load_settings

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    settings = load_settings()
    client = CryptoHistoricalDataClient(
        api_key=settings.alpaca_api_key, secret_key=settings.alpaca_secret_key
    )
    quote = get_price(client)

    print(f"{quote.symbol}  bid={quote.bid}  ask={quote.ask}  spread={quote.spread}")
```

Alpaca's crypto latest-quote response shape (for reference, confirmed
live 2026-07-10):

```python
{'BTC/USD': {
    'ask_price': 64009.4, 'ask_size': 0.7767,
    'bid_price': 63958.996, 'bid_size': 0.7855,
    'symbol': 'BTC/USD',
    'timestamp': datetime(2026, 7, 10, 23, 9, 16, 543660, tzinfo=TzInfo(0)),
}}
```

## Environment Variables / Config

None new — reuses `ALPACA_API_KEY`/`ALPACA_SECRET_KEY` from feature 1.
Note `CryptoHistoricalDataClient` doesn't take `paper`/`url_override` —
Alpaca's crypto market data is the same feed regardless of paper vs
live trading, so there's no environment split to worry about here.

## Acceptance Criteria

- [ ] `get_price(client, symbol="BTC/USD")` returns a `PriceQuote` with
      `bid`/`ask` as `Decimal`, not `float`.
- [ ] Unit test mocks the client with a realistic Alpaca quote response
      and asserts the parsed `PriceQuote` fields, including `spread`,
      with no network access.
- [ ] Unit test confirms an `APIError` from the client is wrapped in
      `MarketDataError` with a clear message, and never includes the
      API key/secret.
- [ ] `python -m crypto_bot.market_data`, run against the real paper
      account, prints a current BTC/USD bid/ask/spread line.
- [ ] README updated with a short note on Alpaca's `BASE/QUOTE` symbol
      format (e.g. `BTC/USD`) and that `CryptoHistoricalDataClient` is a
      separate client from `TradingClient`.

## Open Questions

None.

## Out of Scope / Future Work

- Historical/candlestick (bars) data — will be needed once ATR-based
  stop-loss/take-profit (feature 6) or any auto-entry signal is built.
- Multiple pairs / a watchlist.
- Streaming quotes.
